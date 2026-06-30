from __future__ import annotations
from datetime import date
import pandas as pd
from .base import Provider

# NPS (국민연금) 포트폴리오 데이터는 공개 공시 기반
# 실제 운용: https://fund.nps.or.kr 에서 분기별 공시
# 현재 구현: 최근 알려진 배분 비율을 하드코딩 (분기 공시 업데이트 필요)
# 추후 확장: requests로 공시 파싱 또는 수동 업데이트

NPS_ALLOCATION = {
    # snapshot_date → {asset_class: weight_pct}
    "2024-03-31": {
        "국내주식": 17.8,
        "해외주식": 35.1,
        "국내채권": 27.4,
        "해외채권": 7.0,
        "대체투자": 12.3,
        "단기자금": 0.4,
    },
    "2024-06-30": {
        "국내주식": 16.9,
        "해외주식": 36.4,
        "국내채권": 27.2,
        "해외채권": 7.1,
        "대체투자": 12.0,
        "단기자금": 0.4,
    },
    "2024-09-30": {
        "국내주식": 16.5,
        "해외주식": 37.2,
        "국내채권": 26.9,
        "해외채권": 7.0,
        "대체투자": 12.0,
        "단기자금": 0.4,
    },
}


class PortfolioProvider(Provider):
    name = "portfolio"

    def fetch(self, symbol: str, start: date, end: date) -> pd.Series:
        """Returns total AUM proxy (100 = full allocation, tracks largest weight)."""
        if symbol == "nps":
            snapshots = {
                pd.Timestamp(k): max(v.values())
                for k, v in NPS_ALLOCATION.items()
            }
            s = pd.Series(snapshots, name=symbol).sort_index()
            s = s[(s.index >= pd.Timestamp(start)) & (s.index <= pd.Timestamp(end))]
            return s
        return pd.Series(dtype=float, name=symbol)

    def get_allocation_history(self, symbol: str) -> list[dict]:
        """Returns list of {date, asset_class, weight_pct} dicts."""
        if symbol != "nps":
            return []
        result = []
        for snap_date, alloc in NPS_ALLOCATION.items():
            for asset_class, weight in alloc.items():
                result.append({
                    "snapshot_date": snap_date,
                    "asset_class": asset_class,
                    "weight_pct": weight,
                    "amount_bn": None,
                })
        return result
