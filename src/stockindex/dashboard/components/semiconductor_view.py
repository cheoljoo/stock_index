""""반도체 산업 분석(Semi-Conductor View)" 페이지 — 반도체 업황을 여러 각도에서 한 화면에 모아 본다.

`app.py`의 사이드바 메뉴가 "🔬 반도체 산업 분석"일 때 `render()`가 호출된다. 두 종류의 데이터를 섞어 쓴다:
  - KOSPI200·글로벌 반도체 생산지수·한국 반도체 수출물가지수: 매일 cron이 수집한 시계열
    (`config/indicators.yaml`의 `us_semiconductor_production_index`, `kr_semiconductor_export_price_index`)을 그대로 사용.
  - 삼성전자·SK하이닉스의 주가·PER·EPS: 데드캣/상승추세 페이지와 같은 방식으로 pykrx를 실시간 조회(30분 캐시).

```mermaid
flowchart TD
    A["series_map (cron이 매일 수집)"] --> B["KOSPI·KOSPI200 · 글로벌 반도체 생산지수(FRED) · 수출물가지수(ECOS)\nMin-Max 정규화 비교 차트 1개"]
    E["_load_company_fundamentals (pykrx 실시간, 30분 캐시)"] --> F["삼성전자·SK하이닉스 주가 비교"]
    E --> G["삼성전자·SK하이닉스 PER 비교"]
    E --> H["삼성전자·SK하이닉스 EPS(실적) 비교"]
    I["_load_eps_estimates (yfinance 애널리스트 컨센서스, 30분 캐시)"] --> H
    I --> J["선행EPS(내년 컨센서스) vs 실적 EPS 비교 표"]
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
from stockindex.providers import yfinance_provider as yfp
from stockindex.dashboard.components.charts import line_chart

# 반도체 산업 분석 대상 종목 (KRX 코드 → 회사명)
SEMI_TICKERS = {"005930": "삼성전자", "000660": "SK하이닉스"}
# 선행EPS(애널리스트 컨센서스) 조회용 yfinance 티커 (KRX 코드 + ".KS")
_SEMI_YF_TICKERS = {k: f"{k}.KS" for k in SEMI_TICKERS}


@st.cache_data(ttl=1800)
def _load_company_fundamentals(ticker: str, start: date, end: date):
    """한 종목의 시세(종가)와 투자지표(PER/EPS)를 조회한다 (30분 캐시, 로그인 불필요)."""
    price_volume = krx.get_price_volume(ticker, start, end)
    fundamental = krx.get_fundamental(ticker, start, end)
    return price_volume, fundamental


@st.cache_data(ttl=1800)
def _load_eps_estimates(yf_ticker: str) -> dict:
    """애널리스트 컨센서스 기준 이번연도·선행(내년) EPS 추정치를 가져온다 (30분 캐시)."""
    try:
        return yfp.fetch_eps_estimates(yf_ticker)
    except Exception:
        return {}


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
    with st.expander("📖 이 페이지를 어떻게 해석하면 될까요?", expanded=False):
        st.markdown(
            "**① KOSPI vs KOSPI200**\n"
            "- KOSPI(종합지수)는 코스피 상장 전 종목, KOSPI200은 그중 시가총액 상위 200개만 모은 지수예요. "
            "KOSPI200이 삼성전자·SK하이닉스 같은 대형주 비중이 훨씬 커서, 두 지수의 등락폭이 다르면 "
            "'대형주 vs 중소형주' 온도차를 짐작할 수 있습니다.\n\n"
            "**② 글로벌 반도체 사이클 · 한국 반도체 수출(둘 다 대체지표)**\n"
            "- 반도체는 대표적인 경기민감(사이클) 산업이라, 이 지표들이 바닥을 찍고 올라오면 "
            "업황 회복 신호로, 고점에서 꺾이면 다운사이클 진입 신호로 흔히 해석됩니다.\n"
            "- KOSPI200과 이 대체지표들이 같은 방향으로 움직이면 반도체 업황이 한국 증시 전체를 "
            "끌고 가는 중이라는 뜻이고, 방향이 어긋나면 다른 요인(환율, 개별 종목 이슈 등)이 "
            "더 크게 작용하고 있다는 뜻입니다.\n\n"
            "**③ PER · EPS · 선행EPS**\n"
            "- **EPS(주당순이익)**는 '이미 발표된' 과거 실적 기준값이고, **선행EPS(Forward EPS)**는 "
            "'아직 발표 안 된' 앞으로의 실적에 대한 애널리스트들의 평균 예상치예요.\n"
            "- **선행EPS가 실적 EPS보다 높으면** 시장이 '앞으로 실적이 더 좋아질 것'이라 본다는 뜻이고, "
            "**더 낮으면** '올해보다 둔화될 것'이라 본다는 뜻입니다.\n"
            "- **PER**은 '주가 ÷ EPS'라서, 같은 주가라도 EPS가 낮으면 PER이 높게(비싸 보이게) 나옵니다. "
            "실적이 막 꺾인 시점엔 EPS가 아직 안 떨어져서 PER이 낮아 '싸 보이는' 착시가 생길 수 있는데, "
            "이때 선행EPS를 함께 보면 이 착시를 피할 수 있습니다."
        )

    # ── KOSPI·KOSPI200 · 글로벌 반도체 사이클 · 한국 반도체 수출 비교 ──
    st.subheader("KOSPI·KOSPI200 · 글로벌 반도체 사이클 · 한국 반도체 수출 비교")
    st.caption(
        "단위가 서로 달라(지수 pt vs Index) Min-Max 정규화(구간 내 최솟값=0, 최댓값=100)로 "
        "스케일을 맞춰 한 그래프에서 등락 방향을 비교합니다."
    )
    macro_keys = ["kospi", "kospi200", "us_semiconductor_production_index", "kr_semiconductor_export_price_index"]
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
    # ── 선행EPS(내년 컨센서스) 조회 ────────────────────────
    eps_estimates: dict[str, dict] = {}
    with st.spinner("선행EPS(애널리스트 컨센서스) 조회 중..."):
        for ticker in SEMI_TICKERS:
            est = _load_eps_estimates(_SEMI_YF_TICKERS[ticker])
            if est:
                eps_estimates[ticker] = est

    if eps_map:
        st.markdown("**EPS (주당순이익, 실적, 원)**")
        st.plotly_chart(
            line_chart(eps_map, company_names, title="", height=340, dark=dark, markers=True),
            use_container_width=True,
        )

        if eps_estimates:
            st.markdown("**선행EPS(애널리스트 컨센서스, 내년 예상)**")
            st.warning(
                "⚠️ **직접 비교 주의**: 위 실적 EPS(KRX/pykrx 공식 수치)와 아래 컨센서스(yfinance 애널리스트 "
                "추정치)는 산출 기준(발행주식수·연결 범위 등)이 달라 **절대값이 서로 다른 스케일로 나올 수 "
                "있습니다.** 두 수치를 그대로 나눠 비교하지 말고, ①실적 EPS는 자체 추이(늘고 있는지), "
                "②컨센서스는 최근 90일간 상향/하향 조정됐는지, 각각 따로 해석하세요.",
                icon="⚠️",
            )
            rows = []
            for ticker, name in SEMI_TICKERS.items():
                est = eps_estimates.get(ticker, {})
                forward = est.get("forward_eps")
                forward_90d = est.get("forward_eps_90d_ago")
                revision = None
                if forward is not None and forward_90d not in (None, 0):
                    revision = (forward / forward_90d - 1) * 100
                rows.append({
                    "종목": name,
                    "이번 회계연도 컨센서스(원)": f"{est['current_year_eps']:,.0f}" if est.get("current_year_eps") is not None else "-",
                    "선행EPS(내년 컨센서스, 원)": f"{forward:,.0f}" if forward is not None else "-",
                    "선행EPS 90일전(원)": f"{forward_90d:,.0f}" if forward_90d is not None else "-",
                    "90일간 조정폭(%)": f"{revision:+.1f}" if revision is not None else "-",
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            st.caption(
                "\"90일간 조정폭\"이 양수면 최근 애널리스트들이 내년 실적 전망을 **상향 조정** 중이라는 뜻이고, "
                "음수면 **하향 조정** 중이라는 뜻입니다 — 이 방향성 자체는 실적 EPS와 무관하게 유의미합니다. "
                "출처: yfinance 애널리스트 추정치(현재 시점 스냅샷)."
            )
    if not price_map and not per_map and not eps_map:
        st.warning("삼성전자·SK하이닉스 데이터를 불러오지 못했습니다.")

    st.caption(
        "데이터 출처: KOSPI·KOSPI200(yfinance) · 반도체 생산지수(FRED) · 수출물가지수(한국은행 ECOS) · "
        "PER/EPS/주가(KRX 정보데이터시스템, pykrx) · 선행EPS(yfinance 애널리스트 컨센서스). "
        "본 분석은 투자 조언이 아니며 참고용입니다."
    )
