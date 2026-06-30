from __future__ import annotations
import os
from datetime import date
import requests
import pandas as pd
from tenacity import retry, stop_after_attempt, wait_fixed
from .base import Provider

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"


class FredProvider(Provider):
    name = "fred"

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(5))
    def fetch(self, symbol: str, start: date, end: date) -> pd.Series:
        api_key = os.environ.get("FRED_API_KEY", "")
        if not api_key:
            print(f"    [fred] FRED_API_KEY not set — skipping {symbol}. Get a free key at https://fred.stlouisfed.org/docs/api/api_key.html")
            return pd.Series(dtype=float, name=symbol)
        params = {
            "series_id": symbol,
            "observation_start": str(start),
            "observation_end": str(end),
            "file_type": "json",
            "api_key": api_key,
        }
        resp = requests.get(FRED_BASE, params=params, timeout=30)
        resp.raise_for_status()
        observations = resp.json().get("observations", [])
        if not observations:
            return pd.Series(dtype=float, name=symbol)
        dates, values = [], []
        for obs in observations:
            try:
                val = float(obs["value"])
                dates.append(pd.Timestamp(obs["date"]))
                values.append(val)
            except (ValueError, KeyError):
                continue
        s = pd.Series(values, index=pd.DatetimeIndex(dates), name=symbol)
        return s.sort_index()
