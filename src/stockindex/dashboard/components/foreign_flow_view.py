""""외국인 매매 시작점" 페이지 — 외국인이 모으기 / 던지기 시작한 시점과 누적 순매수.

매일 cron이 받아 둔 캐시만 읽는다 (화면에서 KRX를 조회하지 않는다).
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from stockindex.config.loader import load_settings
from stockindex.core import foreign_flow as ff
from stockindex.providers import krx_provider as krx

_EOK = 1e8   # 억 원
_UP, _DOWN = "#e5484d", "#4f8ff7"


def _chart(net: pd.Series, episodes: list, title: str, dark: bool) -> go.Figure:
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Bar(x=net.index, y=net / _EOK, name="일별 순매수(억)",
                         marker_color=[_UP if v > 0 else _DOWN for v in net]), secondary_y=False)
    cumulative = net.cumsum() / _EOK
    fig.add_trace(go.Scatter(x=net.index, y=cumulative, name="누적 순매수(억)",
                             line=dict(width=2, color="#d9a400")), secondary_y=True)
    for direction, label, symbol, color in ((1, "매수 시작", "triangle-up", _UP), (-1, "매도 시작", "triangle-down", _DOWN)):
        days = [pd.Timestamp(e.start) for e in episodes if e.direction == direction]
        if days:
            fig.add_trace(go.Scatter(x=days, y=cumulative.reindex(days), mode="markers", name=label,
                                     marker=dict(symbol=symbol, size=12, color=color)), secondary_y=True)
    fig.update_layout(title=title, height=440, hovermode="x unified",
                      template="plotly_dark" if dark else "plotly_white",
                      legend=dict(orientation="h", y=-0.15), margin=dict(l=40, r=40, t=50, b=40))
    return fig


def _detail(ticker: str, name: str, min_days: int, min_abs: float, dark: bool) -> None:
    net = ff.cached_net(ticker).dropna()
    state = ff.current_state(net, min_days, min_abs)
    if state is None:
        st.info(f"{name}: 아직 받아 둔 자료가 없습니다. 다음 일일 수집 뒤에 나타납니다.")
        return
    cols = st.columns(3)
    cols[0].metric("현재 상태", state.state)
    cols[1].metric("시작일", str(state.start or "-"), f"{state.days}거래일째" if state.start else None, delta_color="off")
    cols[2].metric(f"누적 순매수 ({state.since} 이후)", f"{state.cumulative / _EOK:+,.0f}억")
    episodes = ff.find_episodes(net, min_days, min_abs)
    st.plotly_chart(_chart(net, episodes, f"{name} 외국인 순매수 (기준일 {state.as_of})", dark), width="stretch")
    if episodes:
        st.dataframe(pd.DataFrame([{
            "시작일": e.start, "확정일": e.confirmed, "마지막 날": e.end,
            "방향": "매수" if e.direction > 0 else "매도", "거래일": e.days, "순매수(억)": round(e.total / _EOK),
        } for e in reversed(episodes)]), hide_index=True, width="stretch")
    else:
        st.caption("기준을 만족하는 흐름이 없습니다.")


def render(dark: bool) -> None:
    st.title("🌏 외국인 매매 시작점")
    default_days = load_settings().screener.foreign_start_days
    left, right = st.columns(2)
    min_days = left.slider("연속 거래일 (N)", 2, 10, default_days)
    min_abs = right.number_input("하루 최소 순매수 규모 (억 원)", 0, 10000, 0) * _EOK
    st.caption(f"외국인 순매수가 같은 방향으로 {min_days}거래일 이어지면 흐름으로 봅니다. 시작일은 그 첫날이며 "
               f"{min_days}번째 날에야 알 수 있습니다. 매일 수집한 KRX 순매수 거래대금 기준입니다.")

    st.subheader("KOSPI 시장 전체")
    _detail(ff.MARKET, "KOSPI", min_days, min_abs, dark)

    st.subheader("KOSPI200 종목")
    universe = krx.cached_kospi200()
    rows = ff.scan_cached(universe, min_days, min_abs)
    if not rows:
        st.info("아직 받아 둔 종목 자료가 없습니다. `scripts/run_daily.py`가 실행된 뒤에 나타납니다.")
        return
    choice = st.radio("보기", ["새로 시작", ff.BUYING, ff.SELLING, "전체"], horizontal=True)
    if choice == "새로 시작":
        shown = [r for r in rows if r["new"]]
    else:
        shown = [r for r in rows if choice == "전체" or r["state"] == choice]
    shown.sort(key=lambda r: abs(r["total"]), reverse=True)
    st.caption(f"{len(shown)} / {len(rows)}종목")
    if shown:
        st.dataframe(pd.DataFrame([{
            "종목": r["name"], "코드": r["ticker"], "상태": r["state"], "시작일": r["start"], "거래일": r["days"],
            "흐름 순매수(억)": round(r["total"] / _EOK), "누적(억)": round(r["cumulative"] / _EOK),
            "누적 시작": r["since"], "기준일": r["as_of"],
        } for r in shown]), hide_index=True, width="stretch")

    names = {r["ticker"]: r["name"] for r in (shown or rows)}
    ticker = st.selectbox("종목 상세", list(names), format_func=lambda t: f"{names[t]} ({t})")
    _detail(ticker, names[ticker], min_days, min_abs, dark)
