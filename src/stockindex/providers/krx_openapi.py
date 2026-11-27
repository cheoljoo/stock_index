"""KRX 공식 Open API(openapi.krx.co.kr) 조회 — 인증키 `KRX_OPENAPI_KEY`.

제공하는 것: 유가증권(KOSPI) 전종목 일별 시세(`sto/stk_bydd_trd`)와 종목 기본정보(`sto/stk_isu_base_info`).
제공하지 않는 것(→ `krx_provider`가 pykrx로 처리): 투자자별 수급, 외국인 지분율, 공매도, PER/EPS,
KOSPI200 구성종목. 코스닥 시세는 별도 서비스 이용 승인이 필요해 여기서는 다루지 않는다.

- 한 번의 호출이 "하루치 전종목"이라, 날짜별로 캐시하면 종목 수와 무관하게 호출 수가 늘지 않는다.
- 데이터는 전 영업일분까지만 제공된다(당일 시세 없음).
- 원본 가격(비수정)이므로 KRX 기준가(종가 - 전일대비)를 이용해 수정주가로 환산한다.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

BASE_URL = "https://data-dbg.krx.co.kr/svc/apis"
_ROOT = Path(__file__).resolve().parents[3]
_HOLIDAY_AFTER_DAYS = 7      # 이보다 오래된 날짜가 비어 있으면 휴장일로 확정해 캐시
_RETRY_EMPTY_SECONDS = 1800  # 최근 날짜가 비어 있으면(미반영) 이 시간 동안은 다시 묻지 않는다

_lock = threading.RLock()
_last_call = 0.0
_stop: str | None = None                     # 401/403/429를 받으면 이 프로세스에서는 중단
_days: dict[str, pd.DataFrame] = {}          # 날짜별 메모리 캐시
_empty_seen: dict[str, float] = {}


class OpenAPIError(Exception):
    """Open API로 데이터를 받지 못했다."""


def _key() -> str:
    return os.environ.get("KRX_OPENAPI_KEY", "").strip()


def available() -> bool:
    return bool(_key()) and _stop is None


def _cache_dir() -> Path:
    return Path(os.environ.get("KRX_CACHE_DIR") or (_ROOT / "data" / "krx_cache")) / "openapi"


def _count_call() -> None:
    path = _cache_dir() / "calls_today.json"
    try:
        st = json.loads(path.read_text())
    except Exception:
        st = {}
    today = date.today().isoformat()
    if st.get("date") != today:
        st = {"date": today, "calls": 0}
    limit = int(os.environ.get("KRX_OPENAPI_MAX_CALLS_PER_DAY", "5000"))
    if st["calls"] >= limit:
        raise OpenAPIError(f"Open API 하루 호출 상한({limit}회) 도달")
    st["calls"] += 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(st))


def _request(path: str, bas_dd: str) -> list[dict]:
    """Open API 1회 호출 → OutBlock_1 행 목록. 휴장일/미반영이면 빈 목록."""
    global _last_call, _stop
    with _lock:
        if not available():
            raise OpenAPIError(_stop or "KRX_OPENAPI_KEY 미설정")
        _count_call()
        wait = float(os.environ.get("KRX_OPENAPI_MIN_INTERVAL", "0.3")) - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()
        try:
            resp = requests.get(f"{BASE_URL}/{path}", params={"basDd": bas_dd},
                                headers={"AUTH_KEY": _key()}, timeout=20)
        except requests.RequestException as e:
            raise OpenAPIError(f"{path}: {type(e).__name__}") from e
        if resp.status_code in (401, 403, 429):
            _stop = f"Open API {resp.status_code} 응답({path}) — 인증키/서비스 이용 승인/호출 한도를 확인하세요."
            print(f"[krx-openapi] ⚠️ {_stop}")
            raise OpenAPIError(_stop)
        try:
            rows = resp.json()["OutBlock_1"]
        except Exception as e:
            raise OpenAPIError(f"{path}: 예상하지 못한 응답(HTTP {resp.status_code})") from e
        return rows


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series.astype(str).str.replace(",", ""), errors="coerce")


_COLUMNS = {"TDD_OPNPRC": "시가", "TDD_HGPRC": "고가", "TDD_LWPRC": "저가", "TDD_CLSPRC": "종가",
            "ACC_TRDVOL": "거래량", "FLUC_RT": "등락률", "CMPPREVDD_PRC": "전일대비"}


def daily_trades(d: date) -> pd.DataFrame:
    """d일의 유가증권 전종목 시세(index=단축코드). 주말·당일 이후·휴장일은 빈 DataFrame."""
    if d.weekday() >= 5 or d >= date.today():
        return pd.DataFrame()
    key = d.strftime("%Y%m%d")
    if key in _days:
        return _days[key]
    path = _cache_dir() / "stk_bydd_trd" / f"{key}.parquet"
    if path.exists():
        df = pd.read_parquet(path)
        _days[key] = df
        return df
    if time.monotonic() - _empty_seen.get(key, -_RETRY_EMPTY_SECONDS) < _RETRY_EMPTY_SECONDS:
        return pd.DataFrame()
    rows = _request("sto/stk_bydd_trd", key)
    if rows:
        raw = pd.DataFrame(rows)
        df = pd.DataFrame({new: _num(raw[old]).values for old, new in _COLUMNS.items()},
                          index=raw["ISU_CD"].astype(str).values)
    else:
        df = pd.DataFrame()
        if (date.today() - d).days <= _HOLIDAY_AFTER_DAYS:
            _empty_seen[key] = time.monotonic()
            return df
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)
    _days[key] = df
    return df


def warm_cache(days: int = 400) -> int:
    """최근 days일의 전종목 시세를 미리 받아 둔다(없는 날짜만 호출). 새로 받은 날짜 수를 돌려준다.

    cron(`run_daily`)이 호출해 두면 대시보드가 첫 조회에서 몇 분씩 기다리지 않는다.
    """
    if not available():
        return 0
    fetched = 0
    d = date.today() - timedelta(days=days)
    try:
        while d < date.today():
            cached = (_cache_dir() / "stk_bydd_trd" / f"{d:%Y%m%d}.parquet").exists()
            if not daily_trades(d).empty and not cached:
                fetched += 1
            d += timedelta(days=1)
    except OpenAPIError as e:
        print(f"[krx-openapi] 캐시 채우기 중단: {e}")
    return fetched


def adjust_prices(df: pd.DataFrame) -> pd.DataFrame:
    """원본 시세(오름차순, '전일대비' 포함)를 수정주가로 환산한다.

    KRX는 액면분할·증자 등이 있으면 그날의 기준가(= 종가 - 전일대비)를 조정해 발표한다.
    기준가가 직전 거래일 종가와 다르면 그 비율을 이전 구간 가격에 곱한다(거래량은 나눈다).
    """
    close, base = df["종가"], df["종가"] - df["전일대비"]
    prev = close.shift(1)
    ratio = (base / prev).where((prev > 0) & (base > 0) & (base != prev), 1.0).fillna(1.0)
    # 각 행의 보정계수 = 그 행보다 "뒤"에 발생한 모든 비율의 곱
    factor = ratio[::-1].cumprod()[::-1].shift(-1).fillna(1.0)
    out = df.drop(columns=["전일대비"]).copy()
    for col in ("시가", "고가", "저가", "종가"):
        out[col] = (out[col] * factor).round().astype("int64")
    out["거래량"] = (out["거래량"] / factor).round().astype("int64")
    return out


def price_volume(ticker: str, start: date, end: date) -> pd.DataFrame | None:
    """한 종목의 [start, end] 일별 수정 OHLCV. columns: 시가, 고가, 저가, 종가, 거래량, 등락률

    Open API로 처리할 수 없으면 None (키 없음/승인 안 됨/호출 실패/유가증권 종목이 아님).
    중간 날짜가 빠진 결과는 지표를 왜곡하므로, 하루라도 실패하면 None을 돌려준다.
    """
    if not available():
        return None
    rows, dates = [], []
    d = start
    try:
        while d <= end:
            day = daily_trades(d)
            if not day.empty and ticker in day.index:
                rows.append(day.loc[ticker])
                dates.append(pd.Timestamp(d))
            d += timedelta(days=1)
    except OpenAPIError as e:
        print(f"[krx-openapi] {ticker} 시세 조회 실패: {e}")
        return None
    if not rows:
        return None
    df = pd.DataFrame(rows, index=pd.DatetimeIndex(dates, name="날짜"))
    return adjust_prices(df)


def stock_names() -> dict[str, str]:
    """유가증권 {단축코드: 약식 종목명}. 7일 캐시, 실패 시 오래된 캐시 또는 빈 dict."""
    path = _cache_dir() / "names.json"
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        cached = {}
    if cached and (date.today() - date.fromisoformat(cached["fetched"])).days <= 7:
        return cached["names"]
    if available():
        d = date.today() - timedelta(days=1)
        try:
            for _ in range(10):                  # 가장 최근 영업일 탐색
                if d.weekday() < 5:
                    rows = _request("sto/stk_isu_base_info", d.strftime("%Y%m%d"))
                    if rows:
                        names = {r["ISU_SRT_CD"]: r["ISU_ABBRV"] for r in rows}
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text(json.dumps({"fetched": date.today().isoformat(), "names": names},
                                                   ensure_ascii=False), encoding="utf-8")
                        return names
                d -= timedelta(days=1)
        except OpenAPIError as e:
            print(f"[krx-openapi] 종목명 조회 실패: {e}")
    return cached.get("names", {})
