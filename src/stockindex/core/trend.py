from __future__ import annotations
from typing import Literal
import numpy as np
import pandas as pd
from scipy import stats

TrendLabel = Literal["up", "down", "flat", "volatile"]

SLOPE_THRESHOLD = 0.001   # normalised slope threshold for up/down
R2_THRESHOLD = 0.5        # R² to distinguish trend vs noise
CV_THRESHOLD = 0.03       # coefficient of variation for flat


def classify_trend(series: pd.Series, window: int = 20) -> TrendLabel:
    s = series.dropna()
    if len(s) < max(5, window // 2):
        return "volatile"
    s = s.iloc[-window:]
    vals = s.values.astype(float)
    x = np.arange(len(vals))
    slope, intercept, r_value, _, _ = stats.linregress(x, vals)
    r2 = r_value ** 2
    mean = np.mean(vals)
    if mean == 0:
        return "volatile"
    norm_slope = slope / abs(mean)
    cv = np.std(vals) / abs(mean)
    if cv < CV_THRESHOLD:
        return "flat"
    if r2 >= R2_THRESHOLD:
        if norm_slope > SLOPE_THRESHOLD:
            return "up"
        if norm_slope < -SLOPE_THRESHOLD:
            return "down"
        return "flat"
    return "volatile"


def group_by_trend(
    series_map: dict[str, pd.Series], windows: dict[str, int]
) -> dict[TrendLabel, list[str]]:
    buckets: dict[TrendLabel, list[str]] = {"up": [], "down": [], "flat": [], "volatile": []}
    for key, s in series_map.items():
        label = classify_trend(s, window=windows.get(key, 20))
        buckets[label].append(key)
    return buckets


def normalize_series(series: pd.Series) -> pd.Series:
    """Normalize to first-day=100 for cross-scale comparison."""
    s = series.dropna()
    if s.empty or s.iloc[0] == 0:
        return s
    return (s / s.iloc[0]) * 100
