"""삼성전자 보통주와 우선주 가운데 언제 어느 쪽을 갖는 것이 유리한가. (github.com/cheoljoo/stock_samsung 의 방법)

가격차이비율 = (보통주 - 우선주) / 우선주 × 100. 과거 window 동안의 25%·75% 분위와 비교한다.
- 기본전략: 비율이 25% 분위보다 낮으면(보통주가 상대적으로 쌈) 보통주, 75%보다 높으면 우선주로 갈아탄다
- 반대전략: 그 반대
전날 종가로 판단해 다음 날 시가에 매매한다.

원본과 다른 점: window는 거래일 수가 아니라 **달력 기간**, 배당은 **보유한 주식의** 배당,
가격은 배당을 반영해 조정하지 않은 종가(액면분할만 반영)라 배당이 두 번 더해지지 않으며, 매매 비용을 뺀다.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

COMMON, PREFERRED = "005930.KS", "005935.KS"
NAMES = {"c": "삼성전자(보통주)", "p": "삼성전자우"}
STRATEGIES = {"basic": "기본전략", "reverse": "반대전략", "hold_c": "보통주 보유", "hold_p": "우선주 보유"}
CAPITAL = 100_000_000
_CACHE = Path(__file__).resolve().parents[3] / "data" / "samsung" / "prices.parquet"
_COLS = ["c_open", "c_close", "c_div", "p_open", "p_close", "p_div"]


def _download(ticker: str, prefix: str) -> pd.DataFrame:
    import yfinance as yf

    h = yf.Ticker(ticker).history(period="max", auto_adjust=False)
    missing = {"Open", "Close", "Volume", "Dividends"} - set(h.columns)
    if h.empty or missing:
        raise ValueError(f"{ticker} 응답 형식이 다릅니다 (없는 열: {missing or '전체'})")
    h.index = pd.to_datetime(h.index.date)
    # 거래가 없는 날(휴장일이 섞여 옴)은 빼되, 배당락일은 남긴다
    h = h[(h["Volume"] > 0) | (h["Dividends"] > 0)]
    return h[["Open", "Close", "Dividends"]].set_axis([f"{prefix}_open", f"{prefix}_close", f"{prefix}_div"], axis=1)


def refresh() -> pd.DataFrame:
    """새로 받아 캐시한다. 받은 자료가 이상하면 캐시를 바꾸지 않고 ValueError."""
    df = _download(COMMON, "c").join(_download(PREFERRED, "p"), how="inner")
    df = df[(df[["c_open", "c_close", "p_open", "p_close"]] > 0).all(axis=1)].sort_index()[_COLS]
    old = load_cached()
    if len(df) < max(250, int(len(old) * 0.99)):
        raise ValueError(f"받은 자료가 너무 적습니다 ({len(df)}일, 저장분 {len(old)}일)")
    common = old.index.intersection(df.index)[:-5]      # 최근 며칠은 정정될 수 있어 뺀다
    if len(common):
        moved = (df.loc[common, ["c_close", "p_close"]] / old.loc[common, ["c_close", "p_close"]] - 1).abs() > 0.01
        if moved.any(axis=1).sum() > 5:
            raise ValueError(f"저장해 둔 과거 종가가 {int(moved.any(axis=1).sum())}일 바뀌었습니다 "
                             f"(액면분할이면 {_CACHE} 를 지우고 다시 받으세요)")
    kept = old.loc[old.index.difference(df.index)]      # 이번 응답에 빠진 날은 저장해 둔 값을 남긴다
    if len(kept):
        df = pd.concat([df, kept]).sort_index()
    _CACHE.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(_CACHE)
    return df


def load_cached() -> pd.DataFrame:
    return pd.read_parquet(_CACHE) if _CACHE.exists() else pd.DataFrame(columns=_COLS)


def with_bands(df: pd.DataFrame, window_years: int) -> pd.DataFrame:
    """가격차이비율과 과거 window의 25%·75% 분위를 붙인다. 자료가 1년(250일) 미만인 구간은 분위가 없다."""
    out = df.copy()
    out["ratio"] = (out["c_close"] - out["p_close"]) / out["p_close"] * 100
    rolling = out["ratio"].rolling(f"{window_years * 365}D", min_periods=250)
    out["q25"], out["q75"] = rolling.quantile(0.25), rolling.quantile(0.75)
    return out


def current_signal(df: pd.DataFrame, window_years: int) -> dict | None:
    bands = with_bands(df, window_years).dropna(subset=["q25", "q75"])
    if bands.empty:
        return None
    last = bands.iloc[-1]
    if last["ratio"] < last["q25"]:
        cheap = "보통주가 상대적으로 쌈"
    elif last["ratio"] > last["q75"]:
        cheap = "우선주가 상대적으로 쌈"
    else:
        cheap = "중립"
    return {"date": bands.index[-1].date(), "ratio": float(last["ratio"]), "q25": float(last["q25"]),
            "q75": float(last["q75"]), "cheap": cheap}


def backtest(bands: pd.DataFrame, start, strategy: str = "basic", cost_pct: float = 0.2,
             capital: float = CAPITAL) -> dict:
    """`start`부터 `capital`원으로 시작한 결과. `bands`는 `with_bands()` 결과(시작일 이전 자료 포함).

    배당은 현금으로 쌓였다가 다음에 갈아탈 때 함께 다시 산다. 갈아타지 않으면 현금으로 남는다.
    """
    data = bands.assign(prev_ratio=bands["ratio"].shift(), prev_q25=bands["q25"].shift(),
                        prev_q75=bands["q75"].shift())
    data = data[data.index >= pd.Timestamp(start)]
    if data.empty:
        raise ValueError("백테스트할 자료가 없습니다")
    held = "p" if strategy == "hold_p" else "c"
    shares = capital / data[f"{held}_open"].iloc[0]
    cash = dividends = costs = 0.0
    values, trades = [], []
    for i, row in enumerate(data.itertuples()):
        if i:       # 시작일에 산 주식은 그날 배당락 대상이 아니다. 배당은 매매 전 보유분에 준다
            income = shares * getattr(row, f"{held}_div")
            cash += income
            dividends += income
        if i and strategy in ("basic", "reverse") and row.prev_ratio == row.prev_ratio and row.prev_q25 == row.prev_q25:
            low, high = row.prev_ratio < row.prev_q25, row.prev_ratio > row.prev_q75
            if strategy == "reverse":
                low, high = high, low
            target = "c" if low else "p" if high else held
            if target != held:
                proceeds = shares * getattr(row, f"{held}_open")
                cost = proceeds * cost_pct / 100
                costs += cost
                cash += proceeds - cost
                shares, cash = cash / getattr(row, f"{target}_open"), 0.0
                trades.append({"date": row.Index.date(), "to": NAMES[target], "ratio": row.prev_ratio,
                               "shares": shares})
                held = target
        values.append(shares * getattr(row, f"{held}_close") + cash)
    series = pd.Series(values, index=data.index)
    return {"values": series, "final": series.iloc[-1], "return_pct": (series.iloc[-1] / capital - 1) * 100,
            "trades": trades, "dividends": dividends, "costs": costs, "holding": NAMES[held],
            "max_drawdown_pct": float((series / series.cummax() - 1).min() * 100)}
