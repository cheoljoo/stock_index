"""지표 시계열을 상향/하향/일정/울퉁불퉁 4가지 추세로 자동 분류한다.

최근 `window`일 구간에 선형회귀를 적합해 기울기(방향)와 R²(추세의 뚜렷함),
변동계수(CV, 평탄함)를 기준으로 분류한다. 대시보드의 "추세별" 뷰에서
같은 방향으로 움직이는 지표들을 한데 모아 비교할 때 사용한다.
"""
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
    """최근 `window`일 구간의 추세를 4가지 라벨 중 하나로 분류한다.

    판정 순서: 데이터 부족 → volatile / 변동계수(CV) < 임계 → flat /
    R² >= 임계이면 기울기 부호로 up·down 판정 / 그 외 volatile.

    Args:
        series: 원본 시계열 (전체 기간; 최근 `window`개만 사용).
        window: 회귀에 사용할 최근 거래일 수.

    Returns:
        "up" | "down" | "flat" | "volatile"
    """
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
    """여러 지표를 각자의 `trend_window`로 분류해 라벨별로 묶는다.

    Args:
        series_map: {지표key: 시계열}.
        windows: {지표key: classify_trend에 쓸 window(일)}. 없으면 기본 20일.

    Returns:
        {"up": [키...], "down": [...], "flat": [...], "volatile": [...]}
    """
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
