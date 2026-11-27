"""외국인이 모으기(매집) 또는 던지기(매도) 시작한 시점을 찾는다. (github.com/cheoljoo/hs 의 방법을 옮긴 것)

규칙: 외국인 순매수가 같은 방향으로 N거래일 이상 이어지면 하나의 "흐름"이다.
시작일은 그 첫날이고, N번째 날이 되어야 확정된다. 순매수가 0이거나 `min_abs` 이하인 날은 흐름을 끊는다.
`hs`는 주식 수를 썼지만 여기 입력은 KRX의 순매수 **거래대금(원)** 이다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from stockindex.providers import krx_provider as krx

MARKET = "KOSPI"          # 시장 전체 조회에 쓰는 키
BUYING, SELLING, UNCLEAR = "모으는 중", "던지는 중", "뚜렷하지 않음"


@dataclass
class Episode:
    start: date            # 흐름 첫날
    confirmed: date        # N번째 날 (이때 알 수 있게 된다)
    end: date              # 흐름 마지막 날
    direction: int         # +1 매수, -1 매도
    days: int
    total: float           # 흐름 동안의 순매수 합 (원)


@dataclass
class FlowState:
    state: str             # 모으는 중 / 던지는 중 / 뚜렷하지 않음
    as_of: date
    start: date | None     # 현재 흐름의 시작일
    days: int              # 현재 흐름의 길이
    total: float           # 현재 흐름의 순매수 합 (원)
    cumulative: float      # 자료 전체 구간의 누적 순매수 (원)
    since: date            # 누적의 시작일
    new_signal: bool = False   # 마지막 거래일에 막 확정된 흐름


def _runs(net: pd.Series, min_abs: float) -> list[tuple[int, pd.Series]]:
    """(방향, 그 방향이 이어진 구간) 목록. 방향 0은 유의미하지 않은 날."""
    s = net.dropna().sort_index()
    if s.empty:
        return []
    direction = (s > min_abs).astype(int) - (s < -min_abs).astype(int)
    group = (direction != direction.shift()).cumsum()
    return [(int(direction[part.index[0]]), part) for _, part in s.groupby(group)]


def find_episodes(net: pd.Series, min_days: int = 3, min_abs: float = 0.0) -> list[Episode]:
    return [
        Episode(part.index[0].date(), part.index[min_days - 1].date(), part.index[-1].date(),
                direction, len(part), float(part.sum()))
        for direction, part in _runs(net, min_abs)
        if direction and len(part) >= min_days
    ]


def current_state(net: pd.Series, min_days: int = 3, min_abs: float = 0.0) -> FlowState | None:
    runs = _runs(net, min_abs)
    if not runs:
        return None
    s = net.dropna().sort_index()
    direction, part = runs[-1]
    active = bool(direction) and len(part) >= min_days
    return FlowState(
        state=(BUYING if direction > 0 else SELLING) if active else UNCLEAR,
        as_of=s.index[-1].date(),
        start=part.index[0].date() if active else None,
        days=len(part) if direction else 0,
        total=float(part.sum()) if direction else 0.0,
        cumulative=float(s.sum()),
        since=s.index[0].date(),
        new_signal=active and len(part) == min_days,
    )


def cached_net(ticker: str) -> pd.Series:
    """받아 둔 캐시의 외국인 순매수 (KRX를 호출하지 않는다)."""
    df = krx.cached_investor_trading(ticker)
    return df["foreign"] if "foreign" in df.columns else pd.Series(dtype=float)


def scan_cached(tickers: dict[str, str], min_days: int = 3, min_abs: float = 0.0) -> list[dict]:
    """종목별 현재 상태. 캐시가 없는 종목은 건너뛴다."""
    rows = []
    for ticker, name in tickers.items():
        st = current_state(cached_net(ticker), min_days, min_abs)
        if st:
            rows.append({"ticker": ticker, "name": name, "state": st.state, "start": st.start, "days": st.days,
                         "total": st.total, "cumulative": st.cumulative, "since": st.since,
                         "as_of": st.as_of, "new": st.new_signal})
    return rows
