"""KOSPI200 전 종목 외국인·기관 수급 스크리너.

`uptrend.signal_investor_twin_buy`는 종목 1개의 "외국인+기관 N일 연속 동반매수/매도"만
판별한다. 여기서는 같은 연속일수 계산을 KOSPI200 구성종목 전체에 반복 적용해,
지금 수급이 몰리는(또는 빠지는) 종목을 찾아낸다.

```mermaid
flowchart LR
    A["krx.get_kospi200_tickers()"] --> B["종목별 루프"]
    B -->|"krx.get_investor_trading()"| C["_streaks() — 동반매수/매도·외국인단독 연속일수"]
    C --> D["FlowScreenResult"]
    D -->|min_days 이상만| E["screen_kospi200() 반환"]

    B -->|"krx.get_foreign_ownership()"| F["compute_ownership_signal() — 지분율 변화·상승일비율·최대일간상승폭"]
    F --> G["OwnershipScreenResult"]
    G -->|"지속증가 또는 급증만"| H["screen_ownership_kospi200() 반환"]
```
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable
import time
import pandas as pd
from stockindex.providers import krx_provider as krx

# `krx.get_kospi200_tickers()`(pykrx get_index_portfolio_deposit_file)가 KRX API 변경으로
# 현재 항상 빈 결과를 반환한다(2026-08 확인). 완전히 죽는 대신, deadcat_view.PRESET_TICKERS와
# 같은 방식으로 KOSPI 대형주 근사 리스트로 폴백한다 — 정식 KOSPI200 전종목이 아님을
# 호출부(run_daily 로그, 대시보드 캡션)에서 반드시 알려야 한다.
FALLBACK_TICKERS = {
    "005930": "삼성전자", "005935": "삼성전자우", "000660": "SK하이닉스", "373220": "LG에너지솔루션",
    "207940": "삼성바이오로직스", "005380": "현대차", "005490": "POSCO홀딩스",
    "035420": "NAVER", "035720": "카카오", "051910": "LG화학", "006400": "삼성SDI",
    "000270": "기아", "068270": "셀트리온", "105560": "KB금융", "055550": "신한지주",
    "352820": "하이브",
}


def get_universe(as_of: date) -> tuple[dict[str, str], bool]:
    """스캔 대상 종목 목록을 구한다. Returns (tickers, is_full_kospi200)."""
    tickers = krx.get_kospi200_tickers(as_of)
    if tickers:
        return tickers, True
    return dict(FALLBACK_TICKERS), False


@dataclass
class ScreenRun:
    results: list["FlowScreenResult"]
    is_full_kospi200: bool
    universe_size: int


@dataclass
class FlowScreenResult:
    ticker: str
    name: str
    twin_buy_streak: int          # 외국인+기관 동반 순매수 연속 거래일
    twin_sell_streak: int         # 외국인+기관 동반 순매도 연속 거래일
    foreign_only_buy_streak: int  # 외국인은 사고 기관은 아닌(매도/보합) 연속 거래일
    latest_close: float | None


def _tail_streak(mask: pd.Series) -> int:
    """`uptrend._tail_streak`와 동일한 로직(가장 최근부터 연속 True인 길이)."""
    streak = 0
    for v in reversed(mask.tolist()):
        if v:
            streak += 1
        else:
            break
    return streak


def compute_streaks(investor: pd.DataFrame) -> tuple[int, int, int]:
    """투자자별 순매수 데이터프레임에서 (동반매수, 동반매도, 외국인단독매수) 연속일수를 계산한다."""
    needed = {"foreign", "institution"}
    if investor is None or investor.empty or not needed.issubset(investor.columns):
        return 0, 0, 0
    df = investor[list(needed)].dropna()
    if df.empty:
        return 0, 0, 0

    twin_buy = (df["foreign"] > 0) & (df["institution"] > 0)
    twin_sell = (df["foreign"] < 0) & (df["institution"] < 0)
    foreign_only_buy = (df["foreign"] > 0) & (df["institution"] <= 0)

    return _tail_streak(twin_buy), _tail_streak(twin_sell), _tail_streak(foreign_only_buy)


def screen_kospi200(
    start: date | None = None,
    end: date | None = None,
    min_days: int = 3,
    lookback_days: int = 30,
    tickers: dict[str, str] | None = None,
    sleep_seconds: float = 0.2,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> ScreenRun:
    """KOSPI200 전 종목을 순회하며 수급 연속일수를 계산, `min_days` 이상인 종목만 반환.

    Args:
        tickers: 생략 시 `get_universe()`로 조회(KOSPI200 API 실패 시 `FALLBACK_TICKERS`).
                 테스트 시 직접 {ticker: name} dict를 주입할 수 있다.
        sleep_seconds: 종목 사이 호출 간격 — KRX 서버 부하를 줄이기 위한 최소한의 배려.
                       200종목 순회라 0.2초만 둬도 전체 실행에 40초 이상 걸린다.
        on_progress: 종목 하나 처리할 때마다 `(done, total, ticker_name)`으로 호출되는 콜백.
                     대시보드에서 진행률 표시줄을 그리는 용도(cron 실행 시엔 생략).

    Returns:
        `ScreenRun(results, is_full_kospi200, universe_size)`. results는 twin_buy_streak
        기준 내림차순 정렬. KRX 로그인이 안 돼 있으면(`krx.krx_authenticated()`가 False)
        빈 결과를 반환한다 — 호출부는 이 경우를 "일시 실패"가 아니라 "설정 필요"로 안내해야 한다.
    """
    if not krx.krx_authenticated():
        return ScreenRun(results=[], is_full_kospi200=False, universe_size=0)

    end = end or date.today()
    start = start or (end - timedelta(days=lookback_days))
    if tickers is not None:
        universe, is_full = tickers, False
    else:
        universe, is_full = get_universe(end)
    if not universe:
        return ScreenRun(results=[], is_full_kospi200=is_full, universe_size=0)

    results: list[FlowScreenResult] = []
    total = len(universe)
    for i, (ticker, name) in enumerate(universe.items(), start=1):
        if on_progress:
            on_progress(i, total, name)
        investor = krx.get_investor_trading(ticker, start, end)
        twin_buy, twin_sell, foreign_only_buy = compute_streaks(investor)
        if max(twin_buy, twin_sell, foreign_only_buy) < min_days:
            if sleep_seconds:
                time.sleep(sleep_seconds)
            continue

        price_volume = krx.get_price_volume(ticker, end - timedelta(days=5), end)
        latest_close = (
            float(price_volume["종가"].iloc[-1])
            if not price_volume.empty and "종가" in price_volume.columns
            else None
        )
        results.append(FlowScreenResult(
            ticker=ticker, name=name,
            twin_buy_streak=twin_buy, twin_sell_streak=twin_sell,
            foreign_only_buy_streak=foreign_only_buy, latest_close=latest_close,
        ))
        if sleep_seconds:
            time.sleep(sleep_seconds)

    results.sort(key=lambda r: r.twin_buy_streak, reverse=True)
    return ScreenRun(results=results, is_full_kospi200=is_full, universe_size=len(universe))


# ── 외국인 지분율(보유 비중) 스크리너 ────────────────────────────────────────
#
# 위의 twin-buy 스크리너는 "며칠 연속 순매수했는지"(거래 횟수/방향)만 본다. 하지만
# 실제로 중요한 건 "외국인 보유 지분율 자체가 늘고 있는지"다 — 순매수가 반복돼도
# 유상증자로 상장주식수가 같이 늘면 지분율은 그대로일 수 있고, 반대로 하루 대량
# 매수만으로 지분율이 크게 뛸 수도 있다. 그래서 별도 지표로 분리한다.

@dataclass
class OwnershipScreenResult:
    ticker: str
    name: str
    change_pct_points: float       # lookback 구간 전체 지분율 변화(%p, 마지막-처음)
    up_day_ratio: float            # lookback 구간 중 지분율이 전일보다 오른 날의 비율
    max_daily_jump: float          # lookback 구간 중 하루 최대 상승폭(%p)
    is_steady_increase: bool       # 꾸준히(변동 적게) 늘고 있는지
    is_spike: bool                 # 특정 하루에 크게 뛴 적이 있는지
    latest_ratio: float
    latest_close: float | None


def compute_ownership_signal(
    ownership: pd.DataFrame,
    steady_min_change: float = 0.5,
    steady_min_up_ratio: float = 0.6,
    spike_min_daily_change: float = 0.3,
) -> tuple[float, float, float, bool, bool]:
    """지분율 시계열에서 (전체변화%p, 상승일비율, 최대일간상승폭%p, 지속증가여부, 급증여부)를 계산.

    Args:
        steady_min_change: "지속 증가"로 인정할 lookback 구간 전체 변화폭(%p) 최소값.
        steady_min_up_ratio: "지속 증가"로 인정할 상승일 비율 최소값(0~1) — 이게 낮으면
                              전체 변화는 커도 하루 급등/급락이 섞인 변동성 케이스일 뿐이다.
        spike_min_daily_change: "일시 급증"으로 인정할 하루 최대 상승폭(%p) 최소값.
    """
    if ownership is None or ownership.empty or "foreign_ratio" not in ownership.columns:
        return 0.0, 0.0, 0.0, False, False
    ratio = ownership["foreign_ratio"].dropna()
    if len(ratio) < 2:
        return 0.0, 0.0, 0.0, False, False

    diffs = ratio.diff().dropna()
    change_total = float(ratio.iloc[-1] - ratio.iloc[0])
    up_ratio = float((diffs > 0).sum() / len(diffs)) if len(diffs) else 0.0
    max_jump = float(diffs.max()) if len(diffs) else 0.0

    is_steady = change_total >= steady_min_change and up_ratio >= steady_min_up_ratio
    is_spike = max_jump >= spike_min_daily_change

    return change_total, up_ratio, max_jump, is_steady, is_spike


def screen_ownership_kospi200(
    start: date | None = None,
    end: date | None = None,
    lookback_days: int = 30,
    steady_min_change: float = 0.5,
    steady_min_up_ratio: float = 0.6,
    spike_min_daily_change: float = 0.3,
    tickers: dict[str, str] | None = None,
    sleep_seconds: float = 0.2,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> ScreenRun:
    """KOSPI200 전 종목을 순회하며 외국인 지분율 변화를 계산해, 지속 증가/일시 급증 종목만 반환.

    `screen_kospi200()`(동반매수 연속일수)과 완전히 독립적인 스크리너 — 매매 "횟수"가
    아니라 실제 "지분율"을 본다. 반환 형태는 재사용을 위해 같은 `ScreenRun`을 쓰되,
    `results`는 `OwnershipScreenResult` 목록이다.
    """
    if not krx.krx_authenticated():
        return ScreenRun(results=[], is_full_kospi200=False, universe_size=0)

    end = end or date.today()
    start = start or (end - timedelta(days=lookback_days))
    if tickers is not None:
        universe, is_full = tickers, False
    else:
        universe, is_full = get_universe(end)
    if not universe:
        return ScreenRun(results=[], is_full_kospi200=is_full, universe_size=0)

    results: list[OwnershipScreenResult] = []
    total = len(universe)
    for i, (ticker, name) in enumerate(universe.items(), start=1):
        if on_progress:
            on_progress(i, total, name)
        ownership = krx.get_foreign_ownership(ticker, start, end)
        change_total, up_ratio, max_jump, is_steady, is_spike = compute_ownership_signal(
            ownership, steady_min_change, steady_min_up_ratio, spike_min_daily_change,
        )
        if not (is_steady or is_spike):
            if sleep_seconds:
                time.sleep(sleep_seconds)
            continue

        latest_ratio = float(ownership["foreign_ratio"].dropna().iloc[-1])
        price_volume = krx.get_price_volume(ticker, end - timedelta(days=5), end)
        latest_close = (
            float(price_volume["종가"].iloc[-1])
            if not price_volume.empty and "종가" in price_volume.columns
            else None
        )
        results.append(OwnershipScreenResult(
            ticker=ticker, name=name,
            change_pct_points=round(change_total, 4), up_day_ratio=round(up_ratio, 3),
            max_daily_jump=round(max_jump, 4), is_steady_increase=is_steady, is_spike=is_spike,
            latest_ratio=round(latest_ratio, 4), latest_close=latest_close,
        ))
        if sleep_seconds:
            time.sleep(sleep_seconds)

    results.sort(key=lambda r: r.change_pct_points, reverse=True)
    return ScreenRun(results=results, is_full_kospi200=is_full, universe_size=len(universe))
