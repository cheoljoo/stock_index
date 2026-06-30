from __future__ import annotations
from datetime import date, datetime, timedelta
import requests
import pandas as pd
from tenacity import retry, stop_after_attempt, wait_fixed
from .base import Provider

CG_BASE = "https://api.coingecko.com/api/v3"
_FREE_LIMIT_DAYS = 364  # free tier: within 365 days


class CoinGeckoProvider(Provider):
    name = "coingecko"

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(10))
    def fetch(self, symbol: str, start: date, end: date) -> pd.Series:
        # Free tier can only access last 364 days
        earliest = date.today() - timedelta(days=_FREE_LIMIT_DAYS)
        if start < earliest:
            start = earliest
        start_ts = int(datetime.combine(start, datetime.min.time()).timestamp())
        end_ts = int(datetime.combine(end, datetime.max.time()).timestamp())
        url = f"{CG_BASE}/coins/{symbol}/market_chart/range"
        resp = requests.get(
            url,
            params={"vs_currency": "usd", "from": start_ts, "to": end_ts},
            timeout=30,
        )
        resp.raise_for_status()
        prices = resp.json().get("prices", [])
        if not prices:
            return pd.Series(dtype=float, name=symbol)
        ts_ms, vals = zip(*prices)
        idx = pd.to_datetime(ts_ms, unit="ms").normalize()
        s = pd.Series(list(vals), index=idx, name=symbol)
        s = s.groupby(s.index).last()  # one value per day
        return s
