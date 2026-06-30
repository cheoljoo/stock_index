from __future__ import annotations
from datetime import date, timedelta
import pandas as pd
import yfinance as yf
from tenacity import retry, stop_after_attempt, wait_fixed
from .base import Provider


class YFinanceProvider(Provider):
    name = "yfinance"

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(5))
    def fetch(self, symbol: str, start: date, end: date) -> pd.Series:
        end_dl = end + timedelta(days=1)  # yfinance end is exclusive
        ticker = yf.Ticker(symbol)
        df = ticker.history(start=str(start), end=str(end_dl), auto_adjust=True)
        if df.empty:
            return pd.Series(dtype=float, name=symbol)
        s = df["Close"].dropna()
        s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
        return s.rename(symbol)
