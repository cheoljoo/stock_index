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
