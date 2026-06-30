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
