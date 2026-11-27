""""삼성_본주.우선주_분석" 페이지 — 가격차이를 이용해 갈아타는 전략과 단순 보유 비교."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from stockindex.core import preferred as pref

_PERIODS = {"3년": 3, "5년": 5, "10년": 10, "20년": 20}
_WINDOWS = (2, 3, 5)


@st.cache_data(ttl=3600, show_spinner="삼성전자 가격·배당 불러오는 중…")
def _load() -> pd.DataFrame:
    cached = pref.load_cached()
    return cached if not cached.empty else pref.refresh()


def _lines(series: dict[str, pd.Series], title: str, ytitle: str, dark: bool) -> go.Figure:
    fig = go.Figure([go.Scatter(x=s.index, y=s.values, name=name) for name, s in series.items()])
    fig.update_layout(title=title, height=400, hovermode="x unified", yaxis_title=ytitle,
                      template="plotly_dark" if dark else "plotly_white",
                      legend=dict(orientation="h", y=-0.15), margin=dict(l=40, r=20, t=50, b=40))
    return fig


def render(dark: bool) -> None:
    st.title("⚖️ 삼성_본주.우선주_분석")
    st.caption("보통주와 우선주 가운데 언제 어느 쪽이 유리한지 봅니다. 가격차이비율 = (보통주 − 우선주) ÷ 우선주. "
               "과거 window의 25% 분위보다 낮으면 보통주가, 75% 분위보다 높으면 우선주가 상대적으로 쌉니다.")
    try:
        df = _load()
    except Exception as e:
        st.error(f"가격 자료를 불러오지 못했습니다: {e}")
        return

    c1, c2, c3 = st.columns(3)
    period = c1.selectbox("비교 기간", list(_PERIODS), index=2)
    window = c2.selectbox("비교 기간(window)", _WINDOWS, index=0, format_func=lambda w: f"{w}년")
    cost = c3.number_input("갈아탈 때 비용 (%)", 0.0, 2.0, 0.2, 0.05)

    signal = pref.current_signal(df, window)
    if signal:
        a, b, c = st.columns(3)
        a.metric(f"가격차이비율 ({signal['date']})", f"{signal['ratio']:.1f}%")
        b.metric("window 25% ~ 75% 분위", f"{signal['q25']:.1f} ~ {signal['q75']:.1f}%")
        c.metric("지금", signal["cheap"])

    bands = pref.with_bands(df, window)
    start = max(df.index[-1] - pd.DateOffset(years=_PERIODS[period]), df.index[0])
    shown = bands[bands.index >= start]
    st.plotly_chart(_lines({"가격차이비율": shown["ratio"], "25% 분위": shown["q25"], "75% 분위": shown["q75"]},
                           f"가격차이비율 (window {window}년)", "%", dark), width="stretch")

    st.subheader(f"전략 비교 — 최근 {period}, 1억 원 시작")
    results = {}
    for w in _WINDOWS:
        wb = pref.with_bands(df, w)
        for key in ("basic", "reverse"):
            results[f"{pref.STRATEGIES[key]} ({w}년)"] = pref.backtest(wb, start, key, cost)
    for key in ("hold_c", "hold_p"):
        results[pref.STRATEGIES[key]] = pref.backtest(bands, start, key, cost)
    st.dataframe(pd.DataFrame([{
        "전략": name, "최종(억)": round(r["final"] / 1e8, 2), "수익률(%)": round(r["return_pct"], 1),
        "매매 횟수": len(r["trades"]), "받은 배당(억)": round(r["dividends"] / 1e8, 2),
        "수익 중 배당(%)": round(r["dividends"] / (r["final"] - pref.CAPITAL) * 100, 1) if r["final"] > pref.CAPITAL else None,
        "매매 비용(억)": round(r["costs"] / 1e8, 3), "최대 낙폭(%)": round(r["max_drawdown_pct"], 1),
        "지금 보유": r["holding"],
    } for name, r in results.items()]), hide_index=True, width="stretch")

    chosen = [f"기본전략 ({window}년)", f"반대전략 ({window}년)", "보통주 보유", "우선주 보유"]
    st.plotly_chart(_lines({n: results[n]["values"] / 1e8 for n in chosen}, "자산 추이 (주식 + 배당 현금)", "억 원", dark),
                    width="stretch")

    name = st.selectbox("매매 기록", [n for n in results if "전략" in n], index=0)
    trades = results[name]["trades"]
    if trades:
        st.dataframe(pd.DataFrame([{
            "매매일": t["date"], "갈아탄 종목": t["to"], "전날 비율(%)": round(t["ratio"], 2), "보유 주수": round(t["shares"], 1),
        } for t in reversed(trades)]), hide_index=True, width="stretch")
    else:
        st.caption("이 기간에는 매매가 없습니다.")

    st.caption(f"자료: Yahoo Finance {df.index[0].date()} ~ {df.index[-1].date()} (우선주 자료 시작일부터). "
               "전날 종가로 판단해 다음 날 시가에 매매하며, 배당은 배당락일에 세전 현금으로 더합니다. 세금은 반영하지 않습니다. "
               "과거 결과이며 앞으로의 수익을 뜻하지 않습니다.")
