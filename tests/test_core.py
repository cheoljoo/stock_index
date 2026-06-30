from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import numpy as np
import pandas as pd
import pytest
from datetime import date, timedelta
import tempfile, os

from stockindex.config.loader import load_settings, load_indicators, load_groups
from stockindex.config.schema import ThresholdLevel, ThresholdCondition
from stockindex.core.trend import classify_trend, group_by_trend, normalize_series
from stockindex.core.alerts import evaluate_threshold
from stockindex.storage import timeseries as ts
from stockindex.storage import db as _db


# ── Config loading ───────────────────────────────────────────────────────────
def test_load_indicators():
    inds = load_indicators()
    assert "sp500" in inds
    assert inds["sp500"].provider == "yfinance"
    assert inds["sp500"].symbol == "^GSPC"


def test_load_groups():
    groups = load_groups()
    assert "global_equity" in groups
    assert "sp500" in groups["global_equity"].members


def test_enabled_filter():
    from stockindex.config.loader import enabled_indicators
    enabled = enabled_indicators()
    assert all(v.enabled for v in enabled.values())


# ── Trend classification ─────────────────────────────────────────────────────
def _make_series(values: list[float]) -> pd.Series:
    idx = pd.date_range("2024-01-01", periods=len(values), freq="D")
    return pd.Series(values, index=idx)


def test_trend_up():
    s = _make_series([100 + i * 2 for i in range(30)])
    assert classify_trend(s, window=20) == "up"


def test_trend_down():
    s = _make_series([200 - i * 2 for i in range(30)])
    assert classify_trend(s, window=20) == "down"


def test_trend_flat():
    s = _make_series([100.0 + np.random.uniform(-0.5, 0.5) for _ in range(30)])
    result = classify_trend(s, window=20)
    assert result in ("flat", "volatile")  # small noise may be volatile


def test_trend_volatile():
    np.random.seed(42)
    s = _make_series([100 + np.random.randn() * 10 for _ in range(30)])
    result = classify_trend(s, window=20)
    assert result in ("volatile", "flat")


def test_normalize():
    s = _make_series([200.0, 210.0, 220.0])
    n = normalize_series(s)
    assert float(n.iloc[0]) == pytest.approx(100.0)
    assert float(n.iloc[1]) == pytest.approx(105.0)


# ── Alerts ───────────────────────────────────────────────────────────────────
def _level(op, value, window=1):
    return ThresholdLevel(
        level="test",
        condition=ThresholdCondition(op=op, value=value, window=window),
        notify="default",
    )


def test_alert_gte_triggered():
    s = _make_series([10, 20, 35])
    assert evaluate_threshold(s, _level(">=", 30)) is True


def test_alert_gte_not_triggered():
    s = _make_series([10, 20, 25])
    assert evaluate_threshold(s, _level(">=", 30)) is False


def test_alert_lte():
    s = _make_series([100, 80, 15])
    assert evaluate_threshold(s, _level("<=", 20)) is True


def test_alert_pct_change_positive():
    s = _make_series([100, 115])
    assert evaluate_threshold(s, _level("pct_change", 10.0, window=1)) is True


def test_alert_pct_change_negative():
    s = _make_series([100, 85])
    assert evaluate_threshold(s, _level("pct_change", -10.0, window=1)) is True


def test_alert_empty_series():
    s = pd.Series(dtype=float)
    assert evaluate_threshold(s, _level(">=", 10)) is False


# ── Storage ──────────────────────────────────────────────────────────────────
def test_timeseries_save_load():
    with tempfile.TemporaryDirectory() as tmp:
        s = _make_series([1.0, 2.0, 3.0])
        ts.save_series(tmp, "test_key", s)
        loaded = ts.load_series(tmp, "test_key")
        assert len(loaded) == 3
        assert float(loaded.iloc[-1]) == pytest.approx(3.0)


def test_timeseries_merge():
    with tempfile.TemporaryDirectory() as tmp:
        s1 = _make_series([1.0, 2.0])
        ts.save_series(tmp, "key", s1)
        idx2 = pd.date_range("2024-01-03", periods=2, freq="D")
        s2 = pd.Series([3.0, 4.0], index=idx2)
        ts.save_series(tmp, "key", s2)
        loaded = ts.load_series(tmp, "key")
        assert len(loaded) == 4


def test_db_alert_dedup():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        _db.init_db(db_path)
        d = date(2024, 1, 1)
        r1 = _db.record_alert(db_path, "vix", "경고", d, 35.0)
        r2 = _db.record_alert(db_path, "vix", "경고", d, 35.0)
        assert r1 is True
        assert r2 is False  # duplicate suppressed
    finally:
        os.unlink(db_path)


def test_db_portfolio_save():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        _db.init_db(db_path)
        rows = [{"asset_class": "국내주식", "weight_pct": 17.8, "amount_bn": None}]
        _db.save_portfolio_snapshot(db_path, "nps", date(2024, 3, 31), rows)
        hist = _db.get_portfolio_history(db_path, "nps")
        assert len(hist) == 1
        assert hist[0]["weight_pct"] == pytest.approx(17.8)
    finally:
        os.unlink(db_path)
