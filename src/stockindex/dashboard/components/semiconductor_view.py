""""반도체 산업 분석(Semi-Conductor View)" 페이지 — 반도체 업황을 여러 각도에서 한 화면에 모아 본다.

`app.py`의 사이드바 메뉴가 "🔬 반도체 산업 분석"일 때 `render()`가 호출된다. 두 종류의 데이터를 섞어 쓴다:
  - KOSPI200·글로벌 반도체 생산지수·한국 반도체 수출물가지수: 매일 cron이 수집한 시계열
    (`config/indicators.yaml`의 `us_semiconductor_production_index`, `kr_semiconductor_export_price_index`)을 그대로 사용.
  - 삼성전자·SK하이닉스의 주가·PER·EPS: 데드캣/상승추세 페이지와 같은 방식으로 pykrx를 실시간 조회(30분 캐시).

```mermaid
flowchart TD
    A["series_map (cron이 매일 수집)"] --> B["KOSPI200 · 글로벌 반도체 생산지수(FRED) · 수출물가지수(ECOS)\n정규화(첫날=100) 비교 차트 1개"]
    E["_load_company_fundamentals (pykrx 실시간, 30분 캐시)"] --> F["삼성전자·SK하이닉스 주가 비교"]
    E --> G["삼성전자·SK하이닉스 PER 비교"]
    E --> H["삼성전자·SK하이닉스 EPS 비교"]
```

## 데이터 출처의 한계 (중요)

"글로벌 반도체 매출(SIA/WSTS 월간 발표)"과 "한국 반도체 수출액(관세청/산업통상자원부 발표)"은
공식 수치가 유료 구독 또는 별도 API 키가 필요해, 이 페이지에서는 **무료로 즉시 사용 가능한
대체지표(proxy)**를 대신 쓴다. 화면에도 이 사실을 명시한다:
  - "글로벌 반도체 사이클"은 미국 연준의 반도체 산업생산지수(IPG3344S)로 근사한다 (미국 국내 생산
    기준이며, 세계 매출액 자체는 아니다).
  - "한국 반도체 수출"은 ECOS 수출물가지수(시스템반도체, 달러기준)로 근사한다 (가격 지수이며,
    수출 금액/물량 자체는 아니다).
"""
from __future__ import annotations
from datetime import date, timedelta
import pandas as pd
import streamlit as st

from stockindex.providers import krx_provider as krx
from stockindex.dashboard.components.charts import line_chart

# 반도체 산업 분석 대상 종목 (KRX)
SEMI_TICKERS = {"005930": "삼성전자", "000660": "SK하이닉스"}


@st.cache_data(ttl=1800)
def _load_company_fundamentals(ticker: str, start: date, end: date):
    """한 종목의 시세(종가)와 투자지표(PER/EPS)를 조회한다 (30분 캐시, 로그인 불필요)."""
    price_volume = krx.get_price_volume(ticker, start, end)
    fundamental = krx.get_fundamental(ticker, start, end)
    return price_volume, fundamental


def render(dark: bool, series_map: dict[str, pd.Series], display_names: dict[str, str]) -> None:
    """반도체 산업 분석 페이지 전체를 그린다.

    Args:
        dark: 다크 테마 여부 (차트 색상 결정).
        series_map: 매일 수집된 전체 지표 시계열 ({지표key: pd.Series}).
        display_names: {지표key: 표시명}.
    """
    st.title("🔬 반도체 산업 분석 (Semi-Conductor View)")
    st.caption(
        "한국 대형 반도체주(삼성전자·SK하이닉스)의 밸류에이션(PER·EPS)·주가와, "
        "KOSPI200·글로벌 반도체 생산·한국 반도체 수출 관련 지표를 한 화면에서 비교합니다."
    )
    st.info(
        "ℹ️ **데이터 한계 안내**: '글로벌 반도체 매출(SIA/WSTS)'과 '한국 반도체 수출액(관세청)'은 "
        "무료 API로 직접 제공되지 않아, 아래에서는 각각 **미국 반도체 생산지수(FRED)**와 "
        "**한국 반도체 수출물가지수(ECOS)**를 대체지표로 사용합니다. 실제 매출액·수출액 수치가 아님에 유의하세요.",
        icon="ℹ️",
    )

    # ── KOSPI200 · 글로벌 반도체 사이클 · 한국 반도체 수출 비교 ──
    st.subheader("KOSPI 200 · 글로벌 반도체 사이클 · 한국 반도체 수출 비교")
    st.caption(
        "단위가 서로 달라(지수 pt vs Index) Min-Max 정규화(구간 내 최솟값=0, 최댓값=100)로 "
        "스케일을 맞춰 한 그래프에서 등락 방향을 비교합니다."
    )
    macro_keys = ["kospi200", "us_semiconductor_production_index", "kr_semiconductor_export_price_index"]
    macro_map = {k: series_map[k] for k in macro_keys if k in series_map and not series_map[k].dropna().empty}
    if macro_map:
        st.plotly_chart(
            line_chart(macro_map, display_names, title="", min_max=True, height=420, dark=dark),
            use_container_width=True,
        )
        missing = [k for k in macro_keys if k not in macro_map]
        if missing:
            st.caption(f"⚠️ 데이터 없음(수집 필요): {', '.join(display_names.get(k, k) for k in missing)}")
    else:
        st.warning("데이터가 없습니다. `make collect`로 먼저 수집해주세요.")

    st.markdown("---")

    # ── 삼성전자 · SK하이닉스 비교 ─────────────────────────
    st.subheader("삼성전자 · SK하이닉스 비교")
    days_back = st.number_input("조회 기간(일)", min_value=90, max_value=1500, value=365, step=30)
    end = date.today()
    start = end - timedelta(days=int(days_back))

    price_map, per_map, eps_map = {}, {}, {}
    with st.spinner("삼성전자·SK하이닉스 데이터 조회 중..."):
        for ticker, name in SEMI_TICKERS.items():
            try:
                price_volume, fundamental = _load_company_fundamentals(ticker, start, end)
            except Exception as e:
                st.error(f"{name} 데이터 조회 실패: {e}")
                continue
            if not price_volume.empty:
                price_map[ticker] = price_volume["종가"]
            if not fundamental.empty:
                per_map[ticker] = fundamental["PER"]
                eps_map[ticker] = fundamental["EPS"]

    company_names = {k: v for k, v in SEMI_TICKERS.items()}

    if price_map:
        st.markdown("**주가 (종가)**")
        st.plotly_chart(
            line_chart(price_map, company_names, title="", height=340, dark=dark),
            use_container_width=True,
        )
    if per_map:
        st.markdown("**PER (주가수익비율)**")
        st.plotly_chart(
            line_chart(per_map, company_names, title="", height=340, dark=dark),
            use_container_width=True,
        )
    if eps_map:
        st.markdown("**EPS (주당순이익, 원)**")
        st.plotly_chart(
            line_chart(eps_map, company_names, title="", height=340, dark=dark),
            use_container_width=True,
        )
    if not price_map and not per_map and not eps_map:
        st.warning("삼성전자·SK하이닉스 데이터를 불러오지 못했습니다.")

    st.caption(
        "데이터 출처: KOSPI200(yfinance) · 반도체 생산지수(FRED) · 수출물가지수(한국은행 ECOS) · "
        "PER/EPS/주가(KRX 정보데이터시스템, pykrx). 본 분석은 투자 조언이 아니며 참고용입니다."
    )
