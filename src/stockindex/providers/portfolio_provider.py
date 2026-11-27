"""국민연금(NPS) 기금의 자산배분 비중을 공식 공개 자료에서 받아온다. 인증키는 필요 없다.

- 기금운용본부 "포트폴리오 현황" 화면: 가장 최근 월말 값(잠정치)
- 공공데이터포털 "국민연금공단_기금 포트폴리오 현황"(15106894, CSV, 월간 갱신): 과거 연말 값과 최근 월말 값

받은 값은 `nps_check`의 검사를 통과해야 SQLite `portfolio_snapshots`에 기준일별로 쌓인다. 대시보드는 DB만 읽는다.
비중(%)은 복지·기타 부문을 포함한 전체 자산 대비다. 어느 한쪽이 실패하면 다른 쪽과 저장된 값을 쓴다.
"""
from __future__ import annotations

import calendar
import csv
import io
import re
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import requests

from stockindex.config.loader import load_settings
from stockindex.storage import db as _db

from . import nps_check
from .base import Provider

SITE_URL = "https://fund.nps.or.kr/oprtprcn/ivsmprcn/getOHED0016M0.do"
_PORTAL = "https://www.data.go.kr"
DATASET_URL = f"{_PORTAL}/data/15106894/fileData.do"

ASSETS = ("국내주식", "해외주식", "국내채권", "해외채권", "대체투자", "단기자금")
OTHER = "복지·기타"
_HEADERS = {"User-Agent": "stock-index-dashboard"}
_TIMEOUT = 30

Snapshots = dict  # {기준일(date): {자산군: 금액(십억 원)}}

CODE_CHECK = "코드 점검 필요"
_ROOT = Path(__file__).resolve().parents[3]
_CHECK_LOG = _ROOT / "logs" / "data_check.log"
_REJECTED = _ROOT / "logs" / "nps_rejected"


def _check_total(d: date, amounts: dict[str, float], reported: float) -> None:
    """자산군 합계가 화면·파일에 적힌 총액과 맞는지 본다. 항목이 빠지거나 단위·열이 바뀌면 어긋난다."""
    total = sum(amounts.values())
    if reported <= 0 or abs(total / reported - 1) > 0.01:
        raise ValueError(f"{d} 자산군 합계 {total:,.0f}가 총액 {reported:,.0f}(십억 원)과 맞지 않습니다")


def parse_site(html: str) -> Snapshots:
    """기금운용본부 화면의 기준월과 도넛 차트 금액(조 원)을 읽는다."""
    m = re.search(r"포트폴리오 개요(?:\s|<[^>]+>)*\(\s*(\d{4})년\s*(\d{1,2})월 말", html)
    if not m:
        raise ValueError("기준월을 찾지 못했습니다")
    if not re.search(r"조\s*원", html):
        raise ValueError("금액 단위 '조 원' 표기를 찾지 못했습니다")
    year, month = int(m[1]), int(m[2])
    d = date(year, month, calendar.monthrange(year, month)[1])
    amounts: dict[str, float] = {}
    financial = 0.0
    for name, value in re.findall(r'\["([^"]+)",\s*"([\d.,]+)"\]', html):
        number = float(value.replace(",", "")) * 1000   # 조 원 → 십억 원
        key = OTHER if name.startswith("복지") else name
        if name == "금융부문":
            financial = financial or number
        elif (key in ASSETS or key == OTHER) and key not in amounts:
            amounts[key] = number
    _require_assets(d, amounts)
    _check_total(d, amounts, financial + amounts.get(OTHER, 0.0))
    return {d: amounts}


def parse_csv(text: str) -> Snapshots:
    """공공데이터포털 CSV. 열 이름 "2026년 7월(...)"은 월말, "2025년(...)"은 연말이다."""
    rows = list(csv.reader(io.StringIO(text.strip())))
    if not rows or rows[0][0].strip() != "구분":
        raise ValueError(f"첫 열이 '구분'이 아닙니다: {rows[:1]}")
    columns = {}
    for i, name in enumerate(rows[0]):
        m = re.match(r"\s*(\d{4})년\s*(?:(\d{1,2})월)?", name)
        if m:
            if "십억" not in name:
                raise ValueError(f"금액 단위가 십억 원이 아닙니다: {name}")
            year, month = int(m[1]), int(m[2] or 12)
            columns[i] = date(year, month, calendar.monthrange(year, month)[1])
    if not columns:
        raise ValueError(f"기준일 열이 없습니다: {rows[0]}")
    out: Snapshots = {d: {} for d in columns.values()}
    reported: dict[date, float] = {}
    for row in rows[1:]:
        label = row[0].strip()
        if label.startswith("전체"):
            reported = {d: float(row[i].replace(",", "")) for i, d in columns.items()}
            continue
        inner = re.match(r"금융부문\((.+)\)", label)
        if inner and inner[1] not in ASSETS:
            raise ValueError(f"처음 보는 자산군입니다: {label}")
        key = inner[1] if inner else (OTHER if label in ("복지부문", "기타부문") else None)
        if key is None:
            continue
        for i, d in columns.items():
            out[d][key] = out[d].get(key, 0.0) + float(row[i].replace(",", ""))
    for d, amounts in out.items():
        _require_assets(d, amounts)
        _check_total(d, amounts, reported.get(d, 0.0))
    return out


def _require_assets(d: date, amounts: dict[str, float]) -> None:
    missing = [a for a in ASSETS if a not in amounts]
    if missing:
        raise ValueError(f"{d} 자산군이 빠졌습니다: {missing}")


def to_snapshot(amounts: dict[str, float]) -> dict[str, tuple[float, float]]:
    """금액을 {자산군: (비중 %, 금액)}으로 바꾼다."""
    total = sum(amounts.values())
    return {k: (round(v / total * 100, 2), round(v, 1)) for k, v in amounts.items()}


def _get(url: str, **params) -> requests.Response:
    response = requests.get(url, params=params or None, headers=_HEADERS, timeout=_TIMEOUT)
    response.raise_for_status()
    return response


def _download_site() -> str:
    return _get(SITE_URL).text


def _download_portal() -> str:
    # 파일이 갱신될 때마다 식별자가 바뀌므로 상세 페이지에서 먼저 읽는다
    page = _get(DATASET_URL).text
    detail = re.search(r'id="publicDataDetailPk"[^>]*value="([^"]+)"', page)
    if not detail:
        raise ValueError("파일 식별자를 찾지 못했습니다")
    info = _get(f"{_PORTAL}/tcs/dss/selectFileDataDownload.do", publicDataPk="15106894",
                publicDataDetailPk=detail[1], fileDetailSn="1").json()
    body = _get(f"{_PORTAL}/cmm/cmm/fileDownload.do", atchFileId=info["atchFileId"],
                fileDetailSn=info.get("fileDetailSn") or "1").content
    try:
        return body.decode("utf-8-sig")
    except UnicodeDecodeError:
        return body.decode("cp949")


def _report(message: str) -> None:
    """실행 로그(결과 메일에 실림)에 찍고, 이력이 남도록 logs/data_check.log에도 덧붙인다."""
    print(f"    [nps] ⚠ {message}")
    _CHECK_LOG.parent.mkdir(parents=True, exist_ok=True)
    with _CHECK_LOG.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M} [nps] {message}\n")


def _keep_raw(raw: dict[str, str]) -> None:
    """코드를 고칠 때 볼 수 있게 문제가 된 원문을 남긴다."""
    _REJECTED.mkdir(parents=True, exist_ok=True)
    for name, text in raw.items():
        (_REJECTED / f"{date.today():%Y%m%d}_{name}").write_text(text, encoding="utf-8")


def stored_snapshots(db_path: str) -> dict:
    out: dict = {}
    for r in _db.get_portfolio_history(db_path, "nps"):
        d = date.fromisoformat(r["snapshot_date"])
        out.setdefault(d, {})[r["asset_class"]] = (r["weight_pct"], r["amount_bn"])
    return out


def refresh(db_path: str, accept: bool = False, write: bool = True) -> int:
    """두 출처에서 받아 검사한 뒤 저장하고, 저장(대상) 기준일 수를 돌려준다.

    형식이 바뀌었거나 값이 이상하면 `코드 점검 필요`를 남기고 그 값은 저장하지 않는다.
    """
    _db.init_db(db_path)
    # 같은 기준일이면 뒤의 것(십억 원 단위라 더 정확한 CSV)을 쓴다
    plan = (("기금운용본부", "site.html", _download_site, parse_site),
            ("공공데이터포털", "portal.csv", _download_portal, parse_csv))
    sources, raw, broken = {}, {}, False
    for label, filename, download, parse in plan:
        try:
            text = download()
            raw[filename] = text
            sources[label] = {d: to_snapshot(a) for d, a in parse(text).items()}
        except (ValueError, KeyError, IndexError, TypeError) as e:
            broken = True
            _report(f"{CODE_CHECK}: {label} 형식이 바뀐 것 같습니다 — {e}")
        except Exception as e:
            _report(f"{label} 접속 실패 (다음 실행에서 다시 시도): {e}")

    accepted, issues = nps_check.check(stored_snapshots(db_path), sources, date.today(), accept=accept)
    for issue in issues:
        _report(f"{'확인 후 반영' if accept else CODE_CHECK}: {issue}")
    if broken or issues:
        _keep_raw(raw)
        print(f"    [nps] ⚠ {CODE_CHECK}: 원문은 {_REJECTED}, 확인은 python scripts/check_nps.py")

    if write:
        for d, snapshot in accepted.items():
            _db.save_portfolio_snapshot(db_path, "nps", d, [
                {"asset_class": k, "weight_pct": w, "amount_bn": a} for k, (w, a) in snapshot.items()])
    return len(accepted)


class PortfolioProvider(Provider):
    """국민연금 자산배분. 지표 시계열 값은 **국내주식 비중(%)**이다."""
    name = "portfolio"

    def fetch(self, symbol: str, start: date, end: date) -> pd.Series:
        """공식 자료를 새로 받은 뒤 저장된 모든 기준일의 국내주식 비중을 돌려준다.

        연 단위 과거 값이 함께 있어야 하므로 `start`로는 자르지 않는다.
        """
        if symbol != "nps":
            return pd.Series(dtype=float, name=symbol)
        refresh(load_settings().storage.db_path)
        points = {pd.Timestamp(r["snapshot_date"]): r["weight_pct"]
                  for r in self.get_allocation_history(symbol) if r["asset_class"] == "국내주식"}
        s = pd.Series(points, name=symbol, dtype=float).sort_index()
        return s[s.index <= pd.Timestamp(end)]

    def get_allocation_history(self, symbol: str) -> list[dict]:
        """저장된 {snapshot_date, asset_class, weight_pct, amount_bn} 목록 (네트워크 호출 없음)."""
        if symbol != "nps":
            return []
        db_path = load_settings().storage.db_path
        _db.init_db(db_path)
        return _db.get_portfolio_history(db_path, "nps")
