from __future__ import annotations
import sys
from pathlib import Path
# Ensure src is on path when run via `streamlit run`
sys.path.insert(0, str(Path(__file__).parents[3]))

import streamlit as st
import pandas as pd
from datetime import date, timedelta

from stockindex.config.loader import (
    load_settings, load_indicators, load_groups, load_thresholds,
)
from stockindex.core.collector import load_all_series
from stockindex.core.trend import group_by_trend, TrendLabel
from stockindex.storage import db as _db
from stockindex.providers.portfolio_provider import PortfolioProvider
from stockindex.dashboard.components.charts import line_chart, portfolio_bar, metric_cards

TREND_LABELS: dict[TrendLabel, str] = {
    "up": "📈 상향",
    "down": "📉 하향",
    "flat": "➡️ 일정",
    "volatile": "〰️ 울퉁불퉁",
}

st.set_page_config(page_title="주식 지표 대시보드", page_icon="📊", layout="wide")


@st.cache_data(ttl=3600)
def _load_data(start: date, end: date):
    return load_all_series(start=start, end=end)


def main():
    settings = load_settings()
    indicators = load_indicators()
    groups = load_groups()
    _, thresholds_cfg = load_thresholds()

    # ── Theme ────────────────────────────────────────────────
    dark = (st.get_option("theme.base") or "light") == "dark"

    # ── Sidebar ──────────────────────────────────────────────
    st.sidebar.title("📊 주식 지표")
    st.sidebar.markdown("---")

    days_back = st.sidebar.slider("조회 기간 (일)", 30, 730, 365, step=30)
    end = date.today()
    start = end - timedelta(days=days_back)

    normalize = st.sidebar.checkbox("정규화 (첫날=100)", value=False)

    view = st.sidebar.radio(
        "뷰 선택",
        ["묶음별", "추세별", "포트폴리오", "알림 현황"],
    )
    st.sidebar.markdown("---")
    st.sidebar.caption("데이터 소스: yfinance · FRED · CoinGecko · 한국은행 ECOS")
    st.sidebar.markdown("---")
    st.sidebar.markdown("[🏠 홈으로](http://psncs.iptime.org/)")

    # ── Load data ────────────────────────────────────────────
    series_map = _load_data(start, end)

    display_names = {k: v.display_name or k for k, v in indicators.items()}
    units = {k: v.unit for k, v in indicators.items()}
    trend_windows = {k: v.trend_window for k, v in indicators.items()}

    # ── Views ────────────────────────────────────────────────
    if view == "묶음별":
        st.title("묶음별 지표")
        group_keys = list(groups.keys())
        selected_group_key = st.selectbox(
            "묶음 선택",
            group_keys,
            format_func=lambda k: groups[k].display_name,
        )
        grp = groups[selected_group_key]
        grp_series = {k: series_map[k] for k in grp.members if k in series_map}

        if not grp_series:
            st.warning("이 묶음에 데이터가 없습니다. 먼저 `run_daily.py`를 실행해주세요.")
        else:
            cards = metric_cards(grp_series, display_names, units)
            cols = st.columns(min(len(cards), 4))
            for i, card in enumerate(cards):
                with cols[i % 4]:
                    st.metric(
                        label=f"{card['name']} ({card['unit']})" if card['unit'] else card['name'],
                        value=f"{card['value']:.2f}",
                        delta=f"{card['delta']:+.2f} ({card['pct']:+.1f}%)",
                    )
            st.plotly_chart(
                line_chart(grp_series, display_names, title=grp.display_name, normalize=normalize, dark=dark),
                use_container_width=True,
            )

    elif view == "추세별":
        st.title("추세별 지표")
        buckets = group_by_trend(series_map, trend_windows)
        for label, label_str in TREND_LABELS.items():
            keys = buckets.get(label, [])
            if not keys:
                continue
            with st.expander(f"{label_str} — {len(keys)}개", expanded=(label == "up")):
                bucket_series = {k: series_map[k] for k in keys if k in series_map}
                st.plotly_chart(
                    line_chart(
                        bucket_series, display_names,
                        title=f"{label_str} 지표 (정규화)",
                        normalize=True,
                        height=350,
                        dark=dark,
                    ),
                    use_container_width=True,
                )
                for k in keys:
                    s = series_map.get(k)
                    if s is not None and not s.empty:
                        st.caption(f"  • {display_names.get(k, k)}: {s.iloc[-1]:.4f} ({units.get(k,'')})")

    elif view == "포트폴리오":
        st.title("국부펀드 포트폴리오")
        prov = PortfolioProvider()
        hist = prov.get_allocation_history("nps")
        if hist:
            st.plotly_chart(portfolio_bar(hist, dark=dark), use_container_width=True)
            df = pd.DataFrame(hist).sort_values(["snapshot_date", "asset_class"])
            pivot = df.pivot(index="snapshot_date", columns="asset_class", values="weight_pct")
            st.dataframe(pivot.style.format("{:.1f}%"), use_container_width=True)
        else:
            st.info("포트폴리오 데이터 없음.")
        st.markdown(
            "**출처**: [국민연금공단 기금운용현황](https://fund.nps.or.kr)  \n"
            "데이터는 분기별 공시 기준입니다."
        )

    elif view == "알림 현황":
        st.title("임계치 알림 현황")
        db_path = settings.storage.db_path
        try:
            rows = _db.recent_alerts(db_path, days=30)
        except Exception:
            rows = []
        if rows:
            df = pd.DataFrame(rows)[["triggered_date", "indicator", "level", "value"]]
            df.columns = ["날짜", "지표", "단계", "값"]
            st.dataframe(df, use_container_width=True)
        else:
            st.info("최근 30일간 임계치 도달 내역 없음.")

        st.markdown("---")
        st.subheader("설정된 임계치")
        for ind, levels in thresholds_cfg.items():
            name = display_names.get(ind, ind)
            for lv in levels:
                cond = lv.condition
                st.caption(
                    f"**{name}** — {lv.level}: {cond.op} {cond.value}"
                    + (f" (window={cond.window}일)" if cond.op == "pct_change" else "")
                )


if __name__ == "__main__":
    main()
