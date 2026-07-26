""""미국 물가(CPI) · 원/달러 환율" 페이지 — 헤드라인/근원 CPI 인플레이션율과 환율을 함께 본다.

`config/indicators.yaml`의 `us_cpi`(Headline CPI), `us_core_cpi`(Core CPI), `usdkrw`(원/달러 환율)를
매일 수집된 Parquet에서 읽어(cron 데이터, 실시간 조회 아님) 표와 그래프로 보여준다.

```mermaid
flowchart TD
    A["load_all_series(us_cpi, us_core_cpi, usdkrw)"] --> B["YoY%(전년동월대비) 계산\n(월별 데이터라 12개월 shift)"]
    B --> C["CPI 요약 표 (지수·YoY% 최근 N개월)"]
    B --> D["CPI 지수 추이 그래프 (Headline vs Core)"]
    B --> E["인플레이션율(YoY%) 그래프 + Fed 목표(2%) 기준선"]
    A --> F["원/달러 환율 추이 그래프"]
```

## 계산 방법

- Headline CPI = FRED `CPIAUCSL` (전체 품목), Core CPI = FRED `CPILFESL` (식품·에너지 제외).
  둘 다 월별 지수(계절조정)이며, 원본 지수 자체보다 **전년동월대비 변화율(YoY%)** 이 보통
  "물가상승률"로 보도되는 수치라 이 페이지에서 직접 계산해 함께 보여준다.
- YoY% 계산에는 12개월 전 값이 필요하므로, 화면에서 고른 조회 기간보다 12개월 더 여유 있게
  데이터를 불러온 뒤 계산하고, 표시할 때만 사용자가 고른 기간으로 잘라낸다.
"""
from __future__ import annotations
from datetime import date, timedelta
import pandas as pd
import streamlit as st

from stockindex.core.collector import load_all_series
from stockindex.dashboard.components.charts import line_chart

FED_TARGET_INFLATION = 2.0


def _yoy_pct(series: pd.Series) -> pd.Series:
    """전년동월대비(YoY) 변화율(%). 월별 데이터 기준 12개월 shift."""
    s = series.dropna()
    return (s / s.shift(12) - 1) * 100


def render(dark: bool) -> None:
    """미국 물가(CPI)·원/달러 환율 페이지 전체를 그린다."""
    st.title("💵 미국 물가(CPI) · 원/달러 환율")
    st.caption(
        "미국 헤드라인 CPI(전체 품목)·근원 CPI(식품·에너지 제외)의 지수와 전년동월대비(YoY) 상승률, "
        "그리고 원/달러 환율 추이를 함께 봅니다."
    )

    with st.expander("📖 이 페이지를 어떻게 해석하면 될까요?", expanded=False):
        st.markdown(
            "**① Headline CPI vs Core CPI**\n"
            "- Headline(전체) CPI는 식품·에너지를 포함한 모든 품목의 물가지수예요. 유가 급등처럼 "
            "일시적 충격에도 크게 흔들립니다.\n"
            "- Core(근원) CPI는 변동성이 큰 식품·에너지를 뺀 지수예요. 연준(Fed)이 통화정책을 "
            "결정할 때 **더 신뢰하는 지표**입니다 — 일시적 유가 변동에 휘둘리지 않고 물가의 "
            "'진짜 추세'를 보기 위해서입니다.\n\n"
            "**② YoY(전년동월대비) 상승률 그래프**\n"
            "- 지수 자체(300 근처의 숫자)는 시간이 갈수록 계속 오르기만 해서 그 자체로는 의미를 "
            "읽기 어려워요. 뉴스에서 말하는 \"물가상승률 3%\" 같은 수치는 대부분 이 **YoY%**입니다.\n"
            "- 점선으로 표시된 **Fed 목표선(2%)**보다 위에 있으면 '물가가 목표보다 뜨겁다' "
            "(연준이 금리를 올리거나 높게 유지할 가능성), 아래에 있으면 '물가 압력이 진정됐다'는 "
            "뜻으로 흔히 해석됩니다.\n"
            "- Headline이 Core보다 훨씬 높으면 최근 유가·식품값 충격이 있었다는 뜻이고, 반대로 "
            "Core가 더 높으면 서비스·임금 등 구조적인 물가 압력이 크다는 뜻으로 봅니다.\n\n"
            "**③ 원/달러 환율(USD/KRW)**\n"
            "- 이 숫자는 \"1달러를 사려면 원화가 얼마나 필요한가\"예요. **숫자가 커질수록(예: 1,300원→1,450원) "
            "원화 가치가 떨어진(약세) 것**이고, 작아지면 원화가 강해진(강세) 것입니다.\n"
            "- 일반적으로 미국 물가상승률이 높아 연준이 금리를 계속 올리면(또는 높게 유지하면), "
            "달러 자산의 매력이 커져 원화 대비 달러가 강세(환율 상승)를 보이는 경향이 있습니다 — "
            "위 CPI/YoY 그래프와 이 환율 그래프를 같이 보면 그 흐름을 함께 확인할 수 있습니다."
        )

    years_back = st.number_input("조회 기간(년)", min_value=2, max_value=20, value=10, step=1)
    end = date.today()
    display_start = end - timedelta(days=365 * int(years_back))
    fetch_start = display_start - timedelta(days=400)  # YoY 계산용 12개월 여유분

    series_map = load_all_series(
        keys=["us_cpi", "us_core_cpi", "usdkrw"], start=fetch_start, end=end,
    )
    headline = series_map.get("us_cpi")
    core = series_map.get("us_core_cpi")
    fx = series_map.get("usdkrw")

    if (headline is None or headline.dropna().empty) and (core is None or core.dropna().empty):
        st.warning("CPI 데이터가 없습니다. `make collect`로 먼저 수집해주세요.")
        return

    headline_yoy = _yoy_pct(headline) if headline is not None else pd.Series(dtype=float)
    core_yoy = _yoy_pct(core) if core is not None else pd.Series(dtype=float)

    # 화면 표시는 사용자가 고른 기간(display_start~end)만 — YoY 계산용 여유분은 계산에만 쓰고 자른다.
    cutoff = pd.Timestamp(display_start)
    headline_d = headline[headline.index >= cutoff] if headline is not None else pd.Series(dtype=float)
    core_d = core[core.index >= cutoff] if core is not None else pd.Series(dtype=float)
    headline_yoy_d = headline_yoy[headline_yoy.index >= cutoff]
    core_yoy_d = core_yoy[core_yoy.index >= cutoff]
    fx_d = fx[fx.index >= cutoff] if fx is not None else pd.Series(dtype=float)

    # ── CPI 요약 표 ──────────────────────────────────────────
    st.subheader("CPI 요약 표 (최근 12개월)")
    table = pd.DataFrame({
        "Headline CPI(지수)": headline_d,
        "Headline YoY(%)": headline_yoy_d,
        "Core CPI(지수)": core_d,
        "Core YoY(%)": core_yoy_d,
    }).sort_index(ascending=False).head(12)
    table.index = table.index.strftime("%Y-%m")
    display_table = table.copy()
    for col in display_table.columns:
        display_table[col] = display_table[col].map(lambda v: f"{v:.2f}" if pd.notna(v) else "-")
    st.dataframe(display_table, use_container_width=True)

    st.markdown("---")

    # ── CPI 지수 추이 (Headline vs Core) ─────────────────────
    st.subheader("CPI 지수 추이 (Headline vs Core)")
    index_map = {}
    if not headline_d.dropna().empty:
        index_map["us_cpi"] = headline_d
    if not core_d.dropna().empty:
        index_map["us_core_cpi"] = core_d
    if index_map:
        st.plotly_chart(
            line_chart(index_map, {"us_cpi": "Headline CPI", "us_core_cpi": "Core CPI"},
                       title="", height=380, dark=dark),
            use_container_width=True,
        )
    else:
        st.info("CPI 지수 데이터가 없습니다.")

    st.markdown("---")

    # ── 인플레이션율(YoY%) 추이 + Fed 목표(2%) 기준선 ─────────
    st.subheader("인플레이션율(YoY%) 추이")
    yoy_map = {}
    if not headline_yoy_d.dropna().empty:
        yoy_map["headline_yoy"] = headline_yoy_d
    if not core_yoy_d.dropna().empty:
        yoy_map["core_yoy"] = core_yoy_d
    if yoy_map:
        fig = line_chart(yoy_map, {"headline_yoy": "Headline CPI YoY(%)", "core_yoy": "Core CPI YoY(%)"},
                          title="", height=380, dark=dark, markers=True)
        fig.add_hline(y=FED_TARGET_INFLATION, line=dict(color="#8892b0", dash="dot", width=1.5),
                      annotation_text=f"Fed 목표 {FED_TARGET_INFLATION:.0f}%", annotation_position="top left")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("YoY 계산에 필요한 12개월치 데이터가 부족합니다. 조회 기간을 늘려보세요.")

    st.markdown("---")

    # ── 원/달러 환율 추이 ─────────────────────────────────────
    st.subheader("원/달러 환율 (USD/KRW) 추이")
    if fx_d is not None and not fx_d.dropna().empty:
        latest = float(fx_d.dropna().iloc[-1])
        prev = float(fx_d.dropna().iloc[-2]) if len(fx_d.dropna()) >= 2 else latest
        st.metric("최근 환율 (1달러당 원화)", f"{latest:,.2f}원", f"{latest - prev:+,.2f}원")
        st.plotly_chart(
            line_chart({"usdkrw": fx_d}, {"usdkrw": "USD/KRW"}, title="", height=340, dark=dark),
            use_container_width=True,
        )
    else:
        st.warning("환율 데이터가 없습니다. `make collect`로 먼저 수집해주세요.")

    st.caption(
        "데이터 출처: 미국 CPI·근원 CPI(FRED CPIAUCSL/CPILFESL), 원/달러 환율(yfinance). "
        "본 분석은 투자 조언이 아니며 참고용입니다."
    )
