from __future__ import annotations
from datetime import date, timedelta
import pandas as pd
import yfinance as yf
from tenacity import retry, stop_after_attempt, wait_fixed
from .base import Provider


class YFinanceProvider(Provider):
    """야후 파이낸스 종가 데이터 (주가지수·ETF·환율·원자재·VIX 등). 무료, 키 불필요."""
    name = "yfinance"

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(5))
    def fetch(self, symbol: str, start: date, end: date) -> pd.Series:
        """일별 종가(Close, 배당·분할 조정) 시계열을 조회한다. 실패 시 최대 3회 재시도."""
        end_dl = end + timedelta(days=1)  # yfinance end is exclusive
        ticker = yf.Ticker(symbol)
        df = ticker.history(start=str(start), end=str(end_dl), auto_adjust=True)
        if df.empty:
            return pd.Series(dtype=float, name=symbol)
        s = df["Close"].dropna()
        s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
        return s.rename(symbol)


@retry(stop=stop_after_attempt(3), wait=wait_fixed(5))
def fetch_ohlcv(symbol: str, start: date, end: date) -> pd.DataFrame:
    """미국 등 해외 종목의 일별 시가/고가/저가/종가/거래량을 조회한다.

    `krx_provider.get_price_volume()`과 같은 컬럼명(시가/고가/저가/종가/거래량)을 써서,
    데드캣·상승추세 분석의 신호 계산 함수들을 KRX 종목과 동일하게 재사용할 수 있게 한다.
    공매도·투자자별 수급은 해외 종목에 대해 제공되지 않으므로 호출부에서 빈 DataFrame으로 채운다.
    """
    end_dl = end + timedelta(days=1)  # yfinance end is exclusive
    ticker = yf.Ticker(symbol)
    df = ticker.history(start=str(start), end=str(end_dl), auto_adjust=True)
    if df.empty:
        return pd.DataFrame()
    df = df.rename(columns={"Open": "시가", "High": "고가", "Low": "저가", "Close": "종가", "Volume": "거래량"})
    df = df[["시가", "고가", "저가", "종가", "거래량"]].dropna(subset=["종가"])
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    df.index.name = "date"
    return df.sort_index()


@retry(stop=stop_after_attempt(3), wait=wait_fixed(5))
def fetch_roic_series(symbol: str) -> pd.Series:
    """연도별 ROIC(투하자본이익률, %)를 계산한다.

    ROIC = NOPAT / Invested Capital
      - NOPAT(세후 영업이익) = EBIT × (1 − 유효세율)
      - Invested Capital: yfinance 대차대조표가 이미 계산해 제공하는 값을 그대로 사용
        (Total Debt + Total Equity − 비영업 현금성자산 등을 반영한 값)

    yfinance 무료 API는 연간 재무제표를 보통 최근 4~5개년치만 제공한다(유료 API처럼
    10년 전체를 주지 않음) — 이 함수는 제공되는 만큼만 반환한다. 데이터가 없으면 빈 Series.
    """
    ticker = yf.Ticker(symbol)
    financials = ticker.financials
    balance_sheet = ticker.balance_sheet
    if financials.empty or balance_sheet.empty:
        return pd.Series(dtype=float, name=symbol)
    if "EBIT" not in financials.index or "Tax Rate For Calcs" not in financials.index:
        return pd.Series(dtype=float, name=symbol)
    if "Invested Capital" not in balance_sheet.index:
        return pd.Series(dtype=float, name=symbol)

    ebit = financials.loc["EBIT"]
    tax_rate = financials.loc["Tax Rate For Calcs"]
    invested_capital = balance_sheet.loc["Invested Capital"]

    years, values = [], []
    for col in financials.columns:
        if col not in invested_capital.index:
            continue
        e, t, ic = ebit.get(col), tax_rate.get(col), invested_capital.get(col)
        if pd.isna(e) or pd.isna(t) or pd.isna(ic) or ic == 0:
            continue
        nopat = e * (1 - t)
        years.append(pd.Timestamp(col))
        values.append(nopat / ic * 100)

    if not years:
        return pd.Series(dtype=float, name=symbol)
    return pd.Series(values, index=pd.DatetimeIndex(years), name=symbol).sort_index()


@retry(stop=stop_after_attempt(3), wait=wait_fixed(5))
def fetch_eps_estimates(symbol: str) -> dict:
    """애널리스트 컨센서스 기준 이번 회계연도(0y)·선행(내년, +1y) EPS 추정치를 가져온다.

    "선행 EPS"는 아직 발표되지 않은 향후 실적에 대한 애널리스트들의 평균 추정치로,
    이미 발표된 실적 기반의 trailing EPS(예: `krx_provider.get_fundamental`의 EPS)와는
    다른 값이다. yfinance의 `Ticker.eps_trend`는 시계열이 아니라 "현재 시점의 추정치
    스냅샷"만 제공하므로, 과거 추이가 아니라 최신 컨센서스 값만 반환한다.

    Returns:
        {"current_year_eps": float | None, "forward_eps": float | None,
         "forward_eps_90d_ago": float | None, "currency": str | None}
        데이터가 없으면 빈 dict.
    """
    ticker = yf.Ticker(symbol)
    try:
        trend = ticker.eps_trend
    except Exception:
        return {}
    if trend is None or trend.empty:
        return {}

    result: dict = {}
    if "currency" in trend.columns and not trend["currency"].empty:
        result["currency"] = trend["currency"].iloc[0]
    if "0y" in trend.index and "current" in trend.columns:
        v = trend.loc["0y", "current"]
        result["current_year_eps"] = float(v) if pd.notna(v) else None
    if "+1y" in trend.index and "current" in trend.columns:
        v = trend.loc["+1y", "current"]
        result["forward_eps"] = float(v) if pd.notna(v) else None
        if "90daysAgo" in trend.columns:
            v90 = trend.loc["+1y", "90daysAgo"]
            result["forward_eps_90d_ago"] = float(v90) if pd.notna(v90) else None
    return result
