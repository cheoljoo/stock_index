import pandas as pd

from stockindex.core import foreign_flow as ff


def _net(values):
    return pd.Series(values, index=pd.bdate_range("2026-01-05", periods=len(values)), dtype=float)


def test_episodes_and_current_state():
    net = _net([5, 5, 5, -1, 2, -3, -3, -3, -3])
    buy, sell = ff.find_episodes(net, 3)
    assert (buy.direction, buy.days, buy.total) == (1, 3, 15) and buy.confirmed == net.index[2].date()
    assert (sell.direction, sell.start, sell.days) == (-1, net.index[5].date(), 4)
    state = ff.current_state(net, 3)
    assert state.state == ff.SELLING and state.days == 4 and not state.new_signal
    assert state.cumulative == net.sum()


def test_new_signal_only_on_confirmation_day_and_min_abs_breaks_streak():
    assert ff.current_state(_net([-1, 4, 4, 4]), 3).new_signal
    assert ff.current_state(_net([4, 4]), 3).state == ff.UNCLEAR
    assert ff.find_episodes(_net([9, 9, 1, 9]), 3, min_abs=2) == []
    assert ff.current_state(pd.Series(dtype=float)) is None
