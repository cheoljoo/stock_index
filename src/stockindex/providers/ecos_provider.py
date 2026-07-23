from __future__ import annotations
import os
from datetime import date
import requests
import pandas as pd
from tenacity import retry, stop_after_attempt, wait_fixed
from .base import Provider

ECOS_BASE = "https://ecos.bok.or.kr/api/StatisticSearch"


class EcosProvider(Provider):
    """한국은행 ECOS Open API provider.

    symbol format: "{stat_code}/{item_code}"
    e.g. "722Y001/0101000" → 기준금리
    Free API key required from https://ecos.bok.or.kr
    """
    name = "ecos"

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(5))
    def fetch(self, symbol: str, start: date, end: date) -> pd.Series:
        """월별 통계값을 조회한다. `ECOS_API_KEY` 미설정 시 제한적인 "sample" 키로 시도."""
        api_key = os.environ.get("ECOS_API_KEY", "sample")
        parts = symbol.split("/")
        stat_code = parts[0]
        item_code = parts[1] if len(parts) > 1 else ""
        start_str = start.strftime("%Y%m")
        end_str = end.strftime("%Y%m")
        url = (
            f"{ECOS_BASE}/{api_key}/json/kr/1/100/"
            f"{stat_code}/M/{start_str}/{end_str}/{item_code}"
        )
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        rows = data.get("StatisticSearch", {}).get("row", [])
        if not rows:
            return pd.Series(dtype=float, name=symbol)
        dates, values = [], []
        for row in rows:
            try:
                dt = pd.Timestamp(row["TIME"] + "01")  # YYYYMM → YYYYMM01
                val = float(row["DATA_VALUE"])
                dates.append(dt)
                values.append(val)
            except (ValueError, KeyError):
                continue
        return pd.Series(values, index=pd.DatetimeIndex(dates), name=symbol).sort_index()
