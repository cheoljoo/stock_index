"""Streamlit 대시보드 진입점.

`make dashboard` 또는 systemd 서비스(`stockindex.service`)가 이 파일을
`streamlit run`으로 실행한다. 데이터 수집(`scripts/run_daily.py`)과는 완전히
분리되어 있으며, 여기서는 저장소(Parquet/SQLite)를 읽거나 데드캣·상승추세
분석처럼 KRX에서 실시간 조회만 할 뿐 아무것도 저장하지 않는다.

```mermaid
flowchart TD
    Start(["사이드바: 메뉴 선택"]) --> P1["📊 주식 지표"]
    Start --> P2["🐈‍⬛ 데드캣 바운스 분석"]
    Start --> P3["📈 상승 추세 전환 분석"]

    P1 --> V1["묶음별"] & V2["추세별"] & V3["포트폴리오"] & V4["알림 현황"]
    V1 & V2 & V3 & V4 -->|load_all_series 로 Parquet 읽기| DataStore[(Parquet/SQLite)]

    P2 -->|deadcat_view.render| KRX["pykrx 실시간 조회"]
    P3 -->|uptrend_view.render| KRX
```
"""
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
from stockindex.dashboard.components import deadcat_view, uptrend_view

TREND_LABELS: dict[TrendLabel, str] = {
    "up": "📈 상향",
    "down": "📉 하향",
    "flat": "➡️ 일정",
    "volatile": "〰️ 울퉁불퉁",
}

st.set_page_config(page_title="주식 지표 대시보드", page_icon="🧭", layout="wide")


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
    st.sidebar.title("🧭 주식 지표 대시보드")
    st.sidebar.markdown("---")

    page = st.sidebar.radio(
        "메뉴", ["📊 주식 지표", "🐈‍⬛ 데드캣 바운스 분석", "📈 상승 추세 전환 분석"],
    )
    st.sidebar.markdown("---")

    view = None
    if page == "📊 주식 지표":
        days_back = st.sidebar.slider("조회 기간 (일)", 30, 730, 365, step=30)
        normalize = st.sidebar.checkbox("정규화 (첫날=100)", value=False)
        view = st.sidebar.radio("뷰 선택", ["묶음별", "추세별", "포트폴리오", "알림 현황"])
        st.sidebar.markdown("---")
    else:
        # 데드캣·상승추세 뷰는 자체적으로 종목·기간을 선택하므로 조회 기간은 미국 지수 비교용 기본값만 사용
        days_back = 365
        normalize = False

    end = date.today()
    start = end - timedelta(days=days_back)

    st.sidebar.caption("데이터 소스: yfinance · FRED · CoinGecko · 한국은행 ECOS")
    st.sidebar.markdown("---")
    st.sidebar.markdown("[🏠 홈으로](http://psncs.iptime.org/)")

    # ── Load data ────────────────────────────────────────────
    series_map = _load_data(start, end)

    display_names = {k: v.display_name or k for k, v in indicators.items()}
    units = {k: v.unit for k, v in indicators.items()}
    trend_windows = {k: v.trend_window for k, v in indicators.items()}

    # ── Views ────────────────────────────────────────────────
    if page == "🐈‍⬛ 데드캣 바운스 분석":
        us_keys = ["nasdaq100", "sp500", "soxx", "smh"]
        us_compare_map = {
            display_names.get(k, k): series_map[k]
            for k in us_keys
            if k in series_map and not series_map[k].dropna().empty
        }
        deadcat_view.render(dark=dark, us_series_map=us_compare_map)
        return

    if page == "📈 상승 추세 전환 분석":
        uptrend_view.render(dark=dark)
        return

    if view == "묶음별":
        st.title("묶음별 지표")
        group_keys = list(groups.keys())
        selected_group_key = st.selectbox(
            "묶음 선택",
            group_keys,
            format_func=lambda k: groups[k].display_name,
        )
        grp = groups[selected_group_key]

        # nps_portfolio는 시계열이 아닌 자산배분 데이터 — 포트폴리오 뷰에서 별도 표시
        non_series = [k for k in grp.members if k == "nps_portfolio"]
        grp_series = {k: series_map[k] for k in grp.members if k in series_map and k != "nps_portfolio"}

        if non_series:
            st.info("📊 국민연금 포트폴리오는 '포트폴리오' 뷰에서 확인하세요.")

        # API 키 미설정으로 수집 실패한 지표 안내
        missing = [k for k in grp.members if k not in series_map and k != "nps_portfolio"]
        if missing:
            missing_names = [display_names.get(k, k) for k in missing]
            st.warning(f"데이터 없는 지표: {', '.join(missing_names)}  \n"
                       "FRED / ECOS API 키가 `.env`에 설정되어 있는지 확인하세요.")

        if not grp_series:
            st.warning("이 묶음에 수집된 데이터가 없습니다.")
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
