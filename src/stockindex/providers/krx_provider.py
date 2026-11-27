"""KRX 데이터 조회 provider — 공식 Open API 우선, 미제공 항목은 data.krx.co.kr(pykrx).

- 시세(`get_price_volume`)·종목명(`get_stock_name`): `KRX_OPENAPI_KEY`가 있으면 Open API(`krx_openapi.py`).
  키가 없거나 처리할 수 없는 종목(코스닥 등)이면 pykrx로 폴백한다.
- 투자자별 수급·외국인 지분율·공매도·PER/EPS·KOSPI200 구성종목: Open API에 없어 pykrx를 쓴다
  (로그인이 필요한 항목은 `KRX_ID`/`KRX_PW`가 없으면 그 기능만 비활성).

아래는 pykrx(data.krx.co.kr) 호출에 적용되는 안전장치다.
KRX는 자동화 수단을 통한 비정상 대량 조회가 감지되면 해당 IP 접속을 1일간 차단한다
(이용약관 제10조 제2호·제6조 제2항 근거). 구체적인 횟수/간격 기준은 공개돼 있지 않아서,
이 모듈은 모든 KRX 호출을 아래 안전장치를 거치도록 한다.

1. **호출 간격(throttle)**: 모든 네트워크 호출 사이에 최소 `KRX_MIN_INTERVAL`초(기본 1.5)
   + 0~0.5초 무작위 지연. pykrx 권고(1초)보다 보수적이다.
2. **호출량 축소**: 종목별 시계열은 `data/krx_cache/`에 저장하고, 이미 받은 구간은 다시
   요청하지 않는다(증분 조회). 구성종목·종목명도 캐시한다. 하루 호출 상한
   `KRX_MAX_CALLS_PER_DAY`(기본 1500)을 넘으면 그날은 더 호출하지 않는다.
3. **로그인 1회**: pykrx는 import 시점에 로그인한다. 모듈 import 때가 아니라 첫 호출 때
   지연 import해 프로세스당 1번만 로그인하며, 로그인이 실패하면(세션 None) pykrx가 호출마다
   재로그인하는 것을 막기 위해 그 프로세스에서는 더 시도하지 않는다.
4. **차단 감지 시 즉시 중단**: KRX가 JSON 대신 HTML 에러 페이지를 주거나 403/429를 주면
   차단으로 보고 `data/krx_block.json`에 기록한다(25시간). 이후 모든 호출은 네트워크 없이
   캐시만 돌려주고, 프로세스를 새로 띄워도 기록이 남아 있는 동안은 KRX에 접속하지 않는다.
   차단이 풀린 게 확실하면 그 파일을 삭제하면 된다.

공개 함수들은 예외를 던지지 않고 실패 시 빈 DataFrame(또는 캐시된 값)을 돌려준다.
호출하는 쪽은 `stop_reason()`으로 "지금 KRX를 쓸 수 없는 이유"를 확인할 수 있다.
"""
from __future__ import annotations

import json
import os
import random
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from stockindex.providers import krx_openapi

_ROOT = Path(__file__).resolve().parents[3]
BLOCK_HOURS = 25


class KRXStop(Exception):
    """더 이상 KRX를 호출하면 안 되는 상황(차단/예산 초과/로그인 실패)."""


class KRXBlocked(KRXStop):
    """KRX가 접속을 제한했다."""


class KRXBudgetExceeded(KRXStop):
    """하루 호출 상한에 도달했다."""


# ── 설정/상태 ────────────────────────────────────────────────────────────────

def _cache_dir() -> Path:
    return Path(os.environ.get("KRX_CACHE_DIR") or (_ROOT / "data" / "krx_cache"))


def _block_file() -> Path:
    return _cache_dir().parent / "krx_block.json"


def _state_file() -> Path:
    return _cache_dir() / "calls_today.json"


def _min_interval() -> float:
    return float(os.environ.get("KRX_MIN_INTERVAL", "1.5"))


def _max_calls_per_day() -> int:
    return int(os.environ.get("KRX_MAX_CALLS_PER_DAY", "1500"))


_lock = threading.RLock()
_last_call = 0.0
_stop: KRXStop | None = None     # 이 프로세스에서 확정된 중단 사유(로그인 실패 등)
_pykrx_stock = None


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _persisted_block() -> str | None:
    info = _read_json(_block_file(), None)
    if not info:
        return None
    try:
        until = datetime.fromisoformat(info["blocked_until"])
    except Exception:
        return None
    if datetime.now() >= until:
        return None
    return (f"KRX 접속이 차단됨 — {until:%Y-%m-%d %H:%M}까지 호출하지 않습니다 "
            f"({info.get('reason', '')}). 해제 확인 후 {_block_file()} 를 삭제하면 재시도합니다.")


def _mark_blocked(reason: str) -> None:
    until = datetime.now() + timedelta(hours=BLOCK_HOURS)
    _write_json(_block_file(), {
        "blocked_until": until.isoformat(timespec="seconds"),
        "detected_at": datetime.now().isoformat(timespec="seconds"),
        "reason": reason[:200],
    })
    print(f"[krx] ⛔ 접속 제한 감지 — {until:%Y-%m-%d %H:%M}까지 KRX 호출을 중단합니다: {reason[:120]}")


def stop_reason() -> str | None:
    """지금 KRX를 호출할 수 없는 이유(없으면 None). 네트워크 호출은 하지 않는다."""
    if _stop is not None:
        return str(_stop)
    blocked = _persisted_block()
    if blocked:
        return blocked
    st = _read_json(_state_file(), {})
    if st.get("date") == date.today().isoformat() and st.get("calls", 0) >= _max_calls_per_day():
        return f"하루 KRX 호출 상한({_max_calls_per_day()}회)에 도달 — 내일 이어서 수집합니다."
    return None


def _check_stop() -> None:
    if _stop is not None:
        raise _stop
    blocked = _persisted_block()
    if blocked:
        raise KRXBlocked(blocked)


def _looks_blocked(exc: BaseException) -> bool:
    """KRX 차단 시그니처: JSON이 아닌 응답(HTML 에러 페이지) 또는 403/429."""
    import json as _json
    if isinstance(exc, _json.JSONDecodeError):
        return True
    try:
        import requests
        if isinstance(exc, requests.exceptions.JSONDecodeError):
            return True
        if isinstance(exc, requests.exceptions.HTTPError):
            code = getattr(exc.response, "status_code", None)
            return code in (403, 429)
    except Exception:
        pass
    return False


def _before_call() -> None:
    """호출 직전: 중단 여부 확인 → 일일 예산 차감 → 최소 간격 보장."""
    global _last_call
    with _lock:
        _check_stop()
        st = _read_json(_state_file(), {})
        today = date.today().isoformat()
        if st.get("date") != today:
            st = {"date": today, "calls": 0}
        if st["calls"] >= _max_calls_per_day():
            raise KRXBudgetExceeded(
                f"하루 KRX 호출 상한({_max_calls_per_day()}회)에 도달 — 내일 이어서 수집합니다.")
        st["calls"] += 1
        _write_json(_state_file(), st)
        wait = _min_interval() + random.uniform(0, 0.5) - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()


def _stock_api():
    """pykrx.stock을 지연 import(= 프로세스당 로그인 1회)."""
    global _pykrx_stock, _stop
    if _pykrx_stock is not None:
        return _pykrx_stock
    with _lock:
        if _pykrx_stock is not None:
            return _pykrx_stock
        _check_stop()
        try:
            from pykrx import stock          # import 시점에 KRX 로그인이 일어난다
            from pykrx.website.comm import auth as _auth
        except Exception as e:
            if _looks_blocked(e):
                _mark_blocked(f"로그인 응답이 JSON이 아님({type(e).__name__})")
                raise KRXBlocked(_persisted_block() or "KRX 접속 차단") from e
            raise
        if krx_authenticated() and getattr(_auth, "_auth_session", None) is None:
            # 로그인 실패(자격 증명 오류 등). 그대로 두면 pykrx가 호출마다 재로그인한다.
            _stop = KRXStop("KRX 로그인 실패 — KRX_ID/KRX_PW를 확인하세요. 이 프로세스에서는 재시도하지 않습니다.")
            raise _stop
        _pykrx_stock = stock
        return stock


def _call(name: str, *args, **kwargs):
    """pykrx.stock.<name>(*args)을 throttle·예산·차단감지와 함께 호출한다."""
    fn = getattr(_stock_api(), name)
    _before_call()
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        if _looks_blocked(e):
            _mark_blocked(f"{name}: JSON이 아닌 응답/접속 거부({type(e).__name__})")
            raise KRXBlocked(_persisted_block() or "KRX 접속 차단") from e
        raise


# ── 인증 ─────────────────────────────────────────────────────────────────────

def krx_authenticated() -> bool:
    return bool(os.environ.get("KRX_ID") and os.environ.get("KRX_PW"))


def check_krx_login() -> tuple[bool, str]:
    """KRX_ID/KRX_PW로 로그인이 되어 있는지 확인한다 (차단 중이면 KRX에 접속하지 않고 사유를 돌려준다).

    반환값: (성공 여부, 사용자에게 보여줄 메시지)
    """
    if not krx_authenticated():
        return False, "KRX_ID/KRX_PW가 설정되지 않았습니다."
    reason = stop_reason()
    if reason:
        return False, reason
    try:
        _stock_api()
        from pykrx.website.comm.auth import get_auth_session
        session = get_auth_session()
    except KRXStop as e:
        return False, str(e)
    except Exception as e:
        return False, f"KRX 로그인 확인 중 오류가 발생했습니다: {e}"
    if session is None:
        return False, "KRX 로그인 실패: KRX_ID 또는 KRX_PW를 확인해주세요."
    return True, "KRX 로그인 성공"


# ── 캐시 ─────────────────────────────────────────────────────────────────────

def _cache_paths(kind: str, ticker: str) -> tuple[Path, Path]:
    base = _cache_dir() / kind
    return base / f"{ticker}.parquet", base / f"{ticker}.json"


def _load_cached(kind: str, ticker: str) -> tuple[pd.DataFrame, dict]:
    pq, meta = _cache_paths(kind, ticker)
    try:
        df = pd.read_parquet(pq) if pq.exists() else pd.DataFrame()
    except Exception:
        df = pd.DataFrame()
    m = _read_json(meta, {})
    if df.empty or "from" not in m or "to" not in m:
        return pd.DataFrame(), {}
    return df, m


def _slice(df: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    return df[(df.index >= pd.Timestamp(start)) & (df.index <= pd.Timestamp(end))].sort_index()


def _cached_fetch(kind: str, ticker: str, start: date, end: date, fetch) -> pd.DataFrame:
    """[start, end] 시계열을 캐시 우선으로 돌려준다 — 캐시에 없는 구간만 `fetch(s, e)`로 받는다.

    - `fetch`는 실패 시 예외를 던지고, 데이터가 없으면 빈 DataFrame을 돌려준다.
    - 오늘 날짜 행은 장중엔 미확정일 수 있어, 확정 구간(`to`)은 어제까지만 인정한다.
      그래서 오늘 데이터는 하루에 한 번(`tail_checked`)만 다시 받는다.
    - 차단/예산 초과(KRXStop) 시에는 네트워크 없이 캐시된 값을 그대로 돌려준다.
    """
    cached, meta = _load_cached(kind, ticker)
    today = date.today()
    settled = today - timedelta(days=1)
    ranges: list[tuple[date, date]] = []
    if not meta:
        ranges.append((start, end))
    else:
        c_from, c_to = date.fromisoformat(meta["from"]), date.fromisoformat(meta["to"])
        if start < c_from:
            ranges.append((start, c_from - timedelta(days=1)))
        if end > c_to and meta.get("tail_checked") != today.isoformat():
            ranges.append((c_to + timedelta(days=1), end))
    if not ranges:
        return _slice(cached, start, end)

    merged = cached
    new_meta = dict(meta)
    try:
        for s, e in ranges:
            df = fetch(s, e)
            if df is not None and not df.empty:
                merged = pd.concat([merged, df]) if not merged.empty else df
                merged = merged[~merged.index.duplicated(keep="last")].sort_index()
            if meta and s > date.fromisoformat(meta["to"]):
                new_meta["tail_checked"] = today.isoformat()
        c_from = min(start, date.fromisoformat(meta["from"])) if meta else start
        c_to = max(min(end, settled), date.fromisoformat(meta["to"])) if meta else min(end, settled)
        if c_to < c_from:
            c_to = c_from - timedelta(days=1)
        new_meta.update({"from": c_from.isoformat(), "to": c_to.isoformat()})
        if not meta and end >= today:
            new_meta["tail_checked"] = today.isoformat()
        pq, mp = _cache_paths(kind, ticker)
        pq.parent.mkdir(parents=True, exist_ok=True)
        if not merged.empty:
            merged.to_parquet(pq)
        _write_json(mp, new_meta)
    except KRXStop:
        pass
    except Exception:
        return _slice(merged if not merged.empty else cached, start, end)
    return _slice(merged, start, end)


# ── 종목명·구성종목 ──────────────────────────────────────────────────────────

def _names_file() -> Path:
    return _cache_dir() / "names.json"


def get_stock_name(ticker: str) -> str:
    official = krx_openapi.stock_names().get(ticker)
    if official:
        return official
    names = _read_json(_names_file(), {})
    if ticker in names:
        return names[ticker]
    try:
        name = _call("get_market_ticker_name", ticker)
    except Exception:
        return ticker
    if isinstance(name, str) and name:
        names[ticker] = name
        _write_json(_names_file(), names)
        return name
    return ticker


# ── 시세/지표 (로그인 불필요) ────────────────────────────────────────────────

def get_price_volume(ticker: str, start: date, end: date) -> pd.DataFrame:
    """일별 수정 OHLCV. columns: 시가, 고가, 저가, 종가, 거래량, 등락률

    Open API(전 영업일까지) 우선, 처리할 수 없으면 pykrx.
    """
    official = krx_openapi.price_volume(ticker, start, end)
    if official is not None:
        return official

    def fetch(s, e):
        df = _call("get_market_ohlcv_by_date", s.strftime("%Y%m%d"), e.strftime("%Y%m%d"), ticker)
        if df is None or df.empty:
            return pd.DataFrame()
        df.index = pd.to_datetime(df.index).normalize()
        return df.sort_index()
    return _cached_fetch("price_volume", ticker, start, end, fetch)


def get_fundamental(ticker: str, start: date, end: date) -> pd.DataFrame:
    """일별 투자지표(DIV/BPS/PER/PBR/EPS/DPS). 로그인 불필요. columns: DIV, BPS, PER, PBR, EPS, DPS"""
    def fetch(s, e):
        df = _call("get_market_fundamental_by_date", s.strftime("%Y%m%d"), e.strftime("%Y%m%d"), ticker)
        if df is None or df.empty:
            return pd.DataFrame()
        df.index = pd.to_datetime(df.index).normalize()
        return df.sort_index()
    return _cached_fetch("fundamental", ticker, start, end, fetch)


# ── 로그인 필요한 데이터 ─────────────────────────────────────────────────────

def get_shorting(ticker: str, start: date, end: date) -> pd.DataFrame:
    """공매도 거래량/비중 + 공매도 잔고/잔고비중. KRX 로그인 필요.

    실패(미로그인 등) 시 빈 DataFrame 반환 — 호출부는 데이터 유무로 판단한다.
    columns: short_volume, short_volume_ratio, short_balance_ratio
    """
    if not krx_authenticated():
        return pd.DataFrame()

    def fetch(s, e):
        fromdate, todate = s.strftime("%Y%m%d"), e.strftime("%Y%m%d")
        errors: list[Exception] = []
        try:
            vol_df = _call("get_shorting_volume_by_date", fromdate, todate, ticker)
        except KRXStop:
            raise
        except Exception as ex:
            errors.append(ex)
            vol_df = pd.DataFrame()
        try:
            bal_df = _call("get_shorting_balance_by_date", fromdate, todate, ticker)
        except KRXStop:
            raise
        except Exception as ex:
            errors.append(ex)
            bal_df = pd.DataFrame()

        if vol_df.empty and bal_df.empty:
            if errors:
                raise errors[0]      # 실패를 "데이터 없음"으로 캐시하지 않는다
            return pd.DataFrame()

        out = pd.DataFrame(index=pd.DatetimeIndex([]))
        if not vol_df.empty:
            vol_df = vol_df.copy()
            vol_df.index = pd.to_datetime(vol_df.index).normalize()
            col = "공매도" if "공매도" in vol_df.columns else "공매도거래량"
            ratio_col = "비중" if "비중" in vol_df.columns else None
            out["short_volume"] = vol_df[col]
            if ratio_col:
                out["short_volume_ratio"] = vol_df[ratio_col]
        if not bal_df.empty:
            bal_df = bal_df.copy()
            bal_df.index = pd.to_datetime(bal_df.index).normalize()
            ratio_col = next((c for c in bal_df.columns if "비중" in c), None)
            if ratio_col:
                out = out.join(bal_df[[ratio_col]].rename(columns={ratio_col: "short_balance_ratio"}), how="outer")
        return out.sort_index()
    return _cached_fetch("shorting", ticker, start, end, fetch)


def get_kospi200_tickers(as_of: date) -> dict[str, str]:
    """KOSPI200 구성종목 {ticker: name}. 로그인 불필요.

    구성종목은 반기에 한 번 바뀌는 수준이라 7일간 캐시한다. `as_of`가 휴장일이면 최근 5일 내에서
    데이터가 나오는 영업일로 보정한다. 실패 시 빈 dict (호출부는 폴백 리스트를 써야 한다).
    """
    cache = _cache_dir() / "kospi200.json"
    c = _read_json(cache, {})
    try:
        if c.get("tickers") and (date.today() - date.fromisoformat(c["fetched"])).days <= 7:
            return c["tickers"]
    except Exception:
        pass
    d = as_of
    try:
        for _ in range(5):
            # pykrx 1.2.x 시그니처는 (ticker, date) — 예전 (date, ticker) 순서로 부르면 항상 빈 결과다.
            try:
                tickers = _call("get_index_portfolio_deposit_file", "1028", date=d.strftime("%Y%m%d"))
            except KRXStop:
                raise
            except Exception:
                tickers = []
            if tickers:
                result = {t: get_stock_name(t) for t in tickers}
                if all(v != k for k, v in result.items()):      # 이름 조회가 끝까지 성공했을 때만 캐시
                    _write_json(cache, {"fetched": date.today().isoformat(), "tickers": result})
                return result
            d -= timedelta(days=1)
    except KRXStop:
        pass
    return c.get("tickers", {}) if c.get("tickers") else {}


def get_foreign_ownership(ticker: str, start: date, end: date) -> pd.DataFrame:
    """일별 외국인 보유 현황(지분율 추이). KRX 로그인 필요.

    "며칠 연속 순매수했는지"가 아니라 "실제 보유 지분율이 얼마나 늘었는지"를 보려면
    이 데이터가 필요하다 — `get_investor_trading`의 순매수 대금은 거래량 기준이라
    지분율 변화와 항상 비례하지 않는다(예: 대량 블록딜, 유상증자로 상장주식수 자체가
    바뀌는 경우 등).

    실패 시 빈 DataFrame. columns: listed_shares(상장주식수), foreign_shares(보유수량),
    foreign_ratio(지분율 %), limit_shares(한도수량), limit_exhaustion(한도소진률 %)
    """
    if not krx_authenticated():
        return pd.DataFrame()

    def fetch(s, e):
        df = _call("get_exhaustion_rates_of_foreign_investment_by_date",
                   s.strftime("%Y%m%d"), e.strftime("%Y%m%d"), ticker)
        if df is None or df.empty:
            return pd.DataFrame()
        df = df.copy()
        df.index = pd.to_datetime(df.index).normalize()
        df = df.rename(columns={
            "상장주식수": "listed_shares", "보유수량": "foreign_shares",
            "지분율": "foreign_ratio", "한도수량": "limit_shares", "한도소진률": "limit_exhaustion",
        })
        return df.sort_index()
    return _cached_fetch("foreign_ownership", ticker, start, end, fetch)


def get_investor_trading(ticker: str, start: date, end: date) -> pd.DataFrame:
    """투자자별(외국인/기관/개인) 순매수 거래대금. KRX 로그인 필요.

    실패 시 빈 DataFrame. columns: foreign, institution, individual
    """
    if not krx_authenticated():
        return pd.DataFrame()

    def fetch(s, e):
        df = _call("get_market_trading_value_by_date", s.strftime("%Y%m%d"), e.strftime("%Y%m%d"), ticker)
        if df is None or df.empty:
            return pd.DataFrame()
        df = df.copy()
        df.index = pd.to_datetime(df.index).normalize()
        rename = {}
        for c in df.columns:
            if "외국인" in c and "기타" not in c:
                rename[c] = "foreign"
            elif "기관" in c and "기타" not in c:
                rename[c] = "institution"
            elif c == "개인":
                rename[c] = "individual"
        return df.rename(columns=rename)[[v for v in rename.values()]].sort_index()
    return _cached_fetch("investor_trading", ticker, start, end, fetch)
