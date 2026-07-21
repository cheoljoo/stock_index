from __future__ import annotations
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from stockindex.core.trend import normalize_series


def _theme_layout(dark: bool) -> dict:
    if dark:
        return dict(
            template="plotly_dark",
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#e0e0e0"),
            xaxis=dict(gridcolor="#2d3154", zerolinecolor="#2d3154", color="#8892b0"),
            yaxis=dict(gridcolor="#2d3154", zerolinecolor="#2d3154", color="#8892b0"),
        )
    else:
        return dict(
            template="plotly",
            plot_bgcolor="white",
            paper_bgcolor="white",
            font=dict(color="#333"),
            xaxis=dict(gridcolor="#eee", zerolinecolor="#eee", color="#333"),
            yaxis=dict(gridcolor="#eee", zerolinecolor="#eee", color="#333"),
        )


def line_chart(
    series_map: dict[str, pd.Series],
    display_names: dict[str, str],
    title: str = "",
    normalize: bool = False,
    height: int = 400,
    dark: bool = False,
) -> go.Figure:
    layout = _theme_layout(dark)
    fig = go.Figure()
    for key, s in series_map.items():
        s = s.dropna()
        if s.empty:
            continue
        y = normalize_series(s) if normalize else s
        name = display_names.get(key, key)
        fig.add_trace(go.Scatter(x=s.index, y=y, mode="lines", name=name))
    fig.update_layout(
        title=title,
        height=height,
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=40, r=20, t=50, b=40),
        **{k: v for k, v in layout.items() if k not in ("xaxis", "yaxis")},
    )
    fig.update_xaxes(
        gridcolor=layout["xaxis"]["gridcolor"],
        zerolinecolor=layout["xaxis"]["zerolinecolor"],
        color=layout["xaxis"]["color"],
    )
    fig.update_yaxes(
        gridcolor=layout["yaxis"]["gridcolor"],
        zerolinecolor=layout["yaxis"]["zerolinecolor"],
        color=layout["yaxis"]["color"],
    )
    return fig


def portfolio_bar(
    history: list[dict],
    title: str = "국민연금 자산배분 추이",
    height: int = 400,
    dark: bool = False,
) -> go.Figure:
    if not history:
        return go.Figure()
    layout = _theme_layout(dark)
    df = pd.DataFrame(history)
    fig = px.bar(
        df,
        x="snapshot_date",
        y="weight_pct",
        color="asset_class",
        barmode="stack",
        title=title,
        height=height,
        labels={"weight_pct": "비중 (%)", "snapshot_date": "날짜", "asset_class": "자산군"},
        template=layout["template"],
    )
    fig.update_layout(
        margin=dict(l=40, r=20, t=50, b=40),
        plot_bgcolor=layout["plot_bgcolor"],
        paper_bgcolor=layout["paper_bgcolor"],
        font=layout["font"],
    )
    return fig


def price_volume_chart(
    price: pd.Series,
    volume: pd.Series,
    low_date=None,
    title: str = "",
    height: int = 420,
    dark: bool = False,
) -> go.Figure:
    """종가(라인, 상단) + 거래량(바, 하단) 콤보 차트. 저점(low_date)을 마커로 표시."""
    from plotly.subplots import make_subplots

    layout = _theme_layout(dark)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.65, 0.35], vertical_spacing=0.04)

    p = price.dropna()
    fig.add_trace(go.Scatter(x=p.index, y=p.values, mode="lines", name="종가", line=dict(color="#4f8ff7")), row=1, col=1)
    if low_date is not None and low_date in p.index:
        fig.add_trace(
            go.Scatter(
                x=[low_date], y=[p.loc[low_date]], mode="markers+text",
                marker=dict(color="#ff4d4f", size=10, symbol="triangle-up"),
                text=["저점"], textposition="bottom center", name="저점",
            ),
            row=1, col=1,
        )

    v = volume.dropna()
    colors = ["#ff4d4f" if i == low_date else "#8892b0" for i in v.index]
    fig.add_trace(go.Bar(x=v.index, y=v.values, name="거래량", marker_color=colors), row=2, col=1)

    fig.update_layout(
        title=title, height=height, hovermode="x unified", showlegend=False,
        margin=dict(l=40, r=20, t=50, b=40),
        **{k: v_ for k, v_ in layout.items() if k not in ("xaxis", "yaxis")},
    )
    for r in (1, 2):
        fig.update_xaxes(gridcolor=layout["xaxis"]["gridcolor"], color=layout["xaxis"]["color"], row=r, col=1)
        fig.update_yaxes(gridcolor=layout["yaxis"]["gridcolor"], color=layout["yaxis"]["color"], row=r, col=1)
    return fig


def shorting_chart(shorting: pd.DataFrame, title: str = "공매도 비중 추이", height: int = 320, dark: bool = False) -> go.Figure:
    layout = _theme_layout(dark)
    fig = go.Figure()
    if "short_volume_ratio" in shorting.columns:
        s = shorting["short_volume_ratio"].dropna()
        fig.add_trace(go.Bar(x=s.index, y=s.values, name="공매도 거래비중(%)", marker_color="#f7a44f"))
    if "short_balance_ratio" in shorting.columns:
        s = shorting["short_balance_ratio"].dropna()
        fig.add_trace(go.Scatter(x=s.index, y=s.values, mode="lines+markers", name="공매도 잔고비중(%)",
                                  line=dict(color="#ff4d4f"), yaxis="y2"))
    fig.update_layout(
        title=title, height=height, hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=40, r=20, t=50, b=40),
        yaxis=dict(title="거래비중(%)"),
        yaxis2=dict(title="잔고비중(%)", overlaying="y", side="right"),
        **{k: v for k, v in layout.items() if k not in ("xaxis", "yaxis")},
    )
    fig.update_xaxes(gridcolor=layout["xaxis"]["gridcolor"], color=layout["xaxis"]["color"])
    return fig


def investor_flow_chart(investor: pd.DataFrame, title: str = "투자자별 순매수 대금", height: int = 320, dark: bool = False) -> go.Figure:
    layout = _theme_layout(dark)
    fig = go.Figure()
    names = {"foreign": "외국인", "institution": "기관", "individual": "개인"}
    colors = {"foreign": "#4f8ff7", "institution": "#7a5cf0", "individual": "#f7a44f"}
    for col, label in names.items():
        if col not in investor.columns:
            continue
        s = investor[col].dropna()
        fig.add_trace(go.Bar(x=s.index, y=s.values, name=label, marker_color=colors[col]))
    fig.update_layout(
        title=title, height=height, barmode="relative", hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=40, r=20, t=50, b=40),
        **{k: v for k, v in layout.items() if k not in ("xaxis", "yaxis")},
    )
    fig.update_xaxes(gridcolor=layout["xaxis"]["gridcolor"], color=layout["xaxis"]["color"])
    fig.update_yaxes(gridcolor=layout["yaxis"]["gridcolor"], color=layout["yaxis"]["color"])
    return fig


def metric_cards(
    series_map: dict[str, pd.Series],
    display_names: dict[str, str],
    units: dict[str, str],
) -> list[dict]:
    cards = []
    for key, s in series_map.items():
        s = s.dropna()
        if s.empty:
            continue
        latest = float(s.iloc[-1])
        prev = float(s.iloc[-2]) if len(s) >= 2 else latest
        delta = latest - prev
        pct = (delta / abs(prev) * 100) if prev != 0 else 0
        cards.append({
            "key": key,
            "name": display_names.get(key, key),
            "value": latest,
            "delta": delta,
            "pct": pct,
            "unit": units.get(key, ""),
            "date": s.index[-1].date(),
        })
    return cards
