import pandas as pd
import pytest

from stockindex.core import preferred as pref


def _bands(ratios, c_div=0.0, p_div=0.0):
    """보통주 가격은 비율에 따라, 우선주는 100원 고정. 분위는 -10/10 고정."""
    idx = pd.bdate_range("2026-01-05", periods=len(ratios))
    c = [100 + r for r in ratios]
    df = pd.DataFrame({"c_open": c, "c_close": c, "c_div": 0.0, "p_open": 100.0, "p_close": 100.0, "p_div": 0.0,
                       "ratio": ratios, "q25": -10.0, "q75": 10.0}, index=idx)
    df.loc[idx[1], ["c_div", "p_div"]] = [c_div, p_div]
    return df


def test_switches_on_previous_day_signal_with_cost():
    r = pref.backtest(_bands([20, 0, 0]), "2026-01-05", "basic", cost_pct=1.0, capital=1200)
    assert [t["to"] for t in r["trades"]] == [pref.NAMES["p"]]      # 첫날 비율 20 > 75% 분위
    assert r["trades"][0]["date"] == pd.Timestamp("2026-01-06").date()
    assert r["final"] == pytest.approx(10 * 100 * 0.99)             # 10주를 100원에 팔고 1% 비용
    assert pref.backtest(_bands([20, 0, 0]), "2026-01-05", "reverse", 0, 1200)["trades"] == []


def test_dividend_follows_held_stock():
    b = _bands([0, 0, 0], c_div=1.0, p_div=7.0)
    assert pref.backtest(b, "2026-01-05", "hold_c", 0, 1000)["dividends"] == pytest.approx(10 * 1)
    assert pref.backtest(b, "2026-01-05", "hold_p", 0, 1000)["dividends"] == pytest.approx(10 * 7)


def test_window_is_calendar_years_and_no_lookahead():
    idx = pd.bdate_range("2020-01-01", "2026-01-01")
    ratio = pd.Series(range(len(idx)), index=idx, dtype=float)
    df = pd.DataFrame({"c_close": 100 + ratio, "p_close": 100.0}, index=idx)
    b = pref.with_bands(df, 2)
    window = b["ratio"][idx[-1] - pd.Timedelta(days=2 * 365) + pd.Timedelta(days=1):]
    assert b["q25"].iloc[-1] == pytest.approx(window.quantile(0.25))
    assert b["q25"].iloc[:249].isna().all() and b["q75"].iloc[300] <= b["ratio"].iloc[300]


def test_day_missing_from_response_is_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(pref, "_CACHE", tmp_path / "p.parquet")
    idx = pd.bdate_range("2020-01-01", periods=400)
    def fake(days):
        return lambda t, p: pd.DataFrame({f"{p}_open": 100.0, f"{p}_close": 100.0, f"{p}_div": 0.0}, index=days)
    monkeypatch.setattr(pref, "_download", fake(idx))
    pref.refresh()
    monkeypatch.setattr(pref, "_download", fake(idx[:-1]))
    assert pref.refresh().index[-1] == idx[-1]
    assert len(pref.load_cached()) == 400


def test_bad_download_keeps_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(pref, "_CACHE", tmp_path / "p.parquet")
    idx = pd.bdate_range("2020-01-01", periods=400)
    def fake(scale):
        return lambda t, p: pd.DataFrame({f"{p}_open": 100.0 * scale, f"{p}_close": 100.0 * scale, f"{p}_div": 0.0}, index=idx)
    monkeypatch.setattr(pref, "_download", fake(1))
    pref.refresh()
    monkeypatch.setattr(pref, "_download", fake(2))
    with pytest.raises(ValueError, match="과거 종가"):
        pref.refresh()
    assert pref.load_cached()["c_close"].iloc[0] == 100
