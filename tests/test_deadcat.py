from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import pandas as pd
import pytest

from stockindex.core import deadcat


def _idx(n, start="2024-01-01"):
    return pd.date_range(start, periods=n, freq="B")


def test_find_recent_low():
    idx = _idx(10)
    close = pd.Series([100, 90, 80, 70, 75, 85, 95, 100, 105, 110], index=idx)
    low_date, low_price = deadcat.find_recent_low(close, lookback=10)
    assert low_date == idx[3]
    assert low_price == pytest.approx(70)


def test_signal_short_covering_dead_cat():
    idx = _idx(15)
    shorting = pd.DataFrame({"short_balance_ratio": [5.0 - i * 0.05 for i in range(15)]}, index=idx)
    investor = pd.DataFrame(
        {"foreign": [1e9] * 3 + [0] * 12, "institution": [0] * 15}, index=idx
    )
    sig = deadcat.signal_short_covering(shorting, investor)
    assert sig["label"] == "dead_cat"


def test_signal_short_covering_real_rebound():
    idx = _idx(15)
    shorting = pd.DataFrame({"short_balance_ratio": [3.0] * 15}, index=idx)
    investor = pd.DataFrame(
        {"foreign": [1e9] * 15, "institution": [1e9] * 15}, index=idx
    )
    sig = deadcat.signal_short_covering(shorting, investor)
    assert sig["label"] == "real_rebound"


def test_signal_short_covering_unknown_without_data():
    sig = deadcat.signal_short_covering(pd.DataFrame(), pd.DataFrame())
    assert sig["label"] == "unknown"


def test_signal_volume_pattern_dead_cat():
    idx = _idx(12)
    volume = [1_000_000] * 6 + [100_000] * 6  # decline heavy, rebound thin
    df = pd.DataFrame({"거래량": volume}, index=idx)
    low_date = idx[5]
    sig = deadcat.signal_volume_pattern(df, low_date)
    assert sig["label"] == "dead_cat"


def test_signal_volume_pattern_real_rebound():
    idx = _idx(12)
    volume = [1_000_000] * 6 + [1_100_000] * 6  # sustained/increasing
    df = pd.DataFrame({"거래량": volume}, index=idx)
    low_date = idx[5]
    sig = deadcat.signal_volume_pattern(df, low_date)
    assert sig["label"] == "real_rebound"


def test_signal_investor_combo_individual_alone():
    idx = _idx(15)
    investor = pd.DataFrame(
        {
            "foreign": [-1e9] * 15,
            "institution": [-1e9] * 15,
            "individual": [2e9] * 15,
        },
        index=idx,
    )
    sig = deadcat.signal_investor_combo(investor)
    assert sig["label"] == "dead_cat"


def test_signal_investor_combo_twin_buy():
    idx = _idx(15)
    investor = pd.DataFrame(
        {
            "foreign": [1e9] * 15,
            "institution": [1e9] * 15,
            "individual": [-2e9] * 15,
        },
        index=idx,
    )
    sig = deadcat.signal_investor_combo(investor)
    assert sig["label"] == "real_rebound"


def test_signal_global_correlation_dead_cat():
    idx = _idx(20)
    kr = pd.Series([100 + i for i in range(20)], index=idx, dtype=float)
    us = pd.Series([100.0] * 20, index=idx)  # flat US market, no co-movement
    sig = deadcat.signal_global_correlation(kr, {"nasdaq100": us})
    assert sig["label"] in ("dead_cat", "unknown")


def test_conclude_dead_cat_majority():
    signals = [
        {"key": "a", "title": "A", "label": "dead_cat", "reason": "r1", "detail": {}},
        {"key": "b", "title": "B", "label": "dead_cat", "reason": "r2", "detail": {}},
        {"key": "c", "title": "C", "label": "real_rebound", "reason": "r3", "detail": {}},
        {"key": "d", "title": "D", "label": "unknown", "reason": "r4", "detail": {}},
    ]
    close = pd.Series([100.0, 105.0], index=_idx(2))
    result = deadcat.conclude(signals, close)
    assert result["verdict"] == "dead_cat_likely"
    assert result["dead_cat_score"] == 2
    assert result["real_rebound_score"] == 1
    assert result["unknown_count"] == 1
    assert result["last_close"] == pytest.approx(105.0)
    assert result["change_pct"] == pytest.approx(5.0)


def test_conclude_inconclusive_no_data():
    signals = [
        {"key": "a", "title": "A", "label": "unknown", "reason": "r1", "detail": {}},
    ]
    result = deadcat.conclude(signals, None)
    assert result["verdict"] == "inconclusive"
