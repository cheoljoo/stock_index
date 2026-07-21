from __future__ import annotations
from datetime import date, timedelta
import pandas as pd
import streamlit as st

from stockindex.providers import krx_provider as krx
from stockindex.core import deadcat
from stockindex.dashboard.components.charts import (
    price_volume_chart, shorting_chart, investor_flow_chart,
)

# 자주 조회되는 대형주 프리셋 (필요시 직접 종목코드 입력 가능)
PRESET_TICKERS = {
    "005930": "삼성전자", "000660": "SK하이닉스", "373220": "LG에너지솔루션",
    "207940": "삼성바이오로직스", "005380": "현대차", "005490": "POSCO홀딩스",
    "035420": "NAVER", "035720": "카카오", "051910": "LG화학", "006400": "삼성SDI",
    "000270": "기아", "068270": "셀트리온", "105560": "KB금융", "055550": "신한지주",
}

LABEL_STYLE = {
    "dead_cat": ("🔻 데드캣 신호", "#ff4d4f"),
    "real_rebound": ("✅ 진짜 반등 신호", "#2ecc71"),
    "neutral": ("➖ 중립", "#8892b0"),
    "unknown": ("❔ 데이터 없음", "#8892b0"),
}


@st.cache_data(ttl=1800)
def _check_krx_login():
    return krx.check_krx_login()


@st.cache_data(ttl=1800)
def _load_ticker_data(ticker: str, start: date, end: date):
    price_volume = krx.get_price_volume(ticker, start, end)
    shorting = krx.get_shorting(ticker, start, end)
    investor = krx.get_investor_trading(ticker, start, end)
    name = krx.get_stock_name(ticker)
    return price_volume, shorting, investor, name


def render(dark: bool, us_series_map: dict[str, pd.Series]) -> None:
    st.title("🐈‍⬛ 데드캣 바운스 분석")
    st.caption(
        "폭락 후 반등이 **일시적 기술적 반등(데드캣 바운스)**인지 **진짜 추세 전환**인지, "
        "공매도·거래량·투자자별(외국인/기관/개인) 수급을 기준으로 판별합니다."
    )

    if not krx.krx_authenticated():
        st.warning(
            "공매도·투자자별 수급 데이터는 **KRX(data.krx.co.kr) 무료 회원 로그인**이 필요합니다.  \n"
            "`.env`에 `KRX_ID`, `KRX_PW`를 설정하면 전체 지표가 표시됩니다. "
            "미설정 시 주가·거래량 기반 분석만 제공됩니다.",
            icon="🔑",
        )
    else:
        login_ok, login_msg = _check_krx_login()
        if not login_ok:
            st.error(
                f"**{login_msg}**  \n"
                "`.env`의 `KRX_ID`, `KRX_PW`를 확인해주세요. "
                "로그인 실패 시 공매도·투자자별 수급 데이터는 표시되지 않습니다.",
                icon="🚫",
            )

    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        preset = st.selectbox(
            "종목 선택",
            list(PRESET_TICKERS.keys()),
            format_func=lambda t: f"{PRESET_TICKERS[t]} ({t})",
        )
    with col2:
        custom = st.text_input("직접 입력 (6자리 종목코드)", value="")
    with col3:
        days_back = st.number_input("조회 기간(일)", min_value=30, max_value=180, value=60, step=10)

    ticker = custom.strip() if custom.strip() else preset
    end = date.today()
    start = end - timedelta(days=int(days_back))

    with st.spinner(f"{ticker} 데이터 조회 중..."):
        try:
            price_volume, shorting, investor, name = _load_ticker_data(ticker, start, end)
        except Exception as e:
            st.error(f"데이터 조회 실패: {e}")
            return

    if price_volume.empty:
        st.error(f"'{ticker}' 종목의 시세 데이터를 찾을 수 없습니다. 종목코드를 확인해주세요.")
        return

    close = price_volume["종가"]
    low_date, low_price = deadcat.find_recent_low(close, lookback=40)

    # ── 차트 (주가·거래량·이평선, 최상단) ──────────────────────
    st.subheader("주가 · 거래량 (5/20/50일 이평선)")
    st.plotly_chart(
        price_volume_chart(close, price_volume["거래량"], low_date=low_date, title=f"{name} 종가·거래량", dark=dark),
        use_container_width=True,
    )
    st.markdown("---")

    # ── 지표 설명 ────────────────────────────────────────────
    with st.expander("📖 판별 지표 설명 (4가지 기준)", expanded=False):
        st.markdown(
            """
| # | 지표 | 데드캣 바운스(가짜 반등) | 진짜 반등(추세 전환) |
|---|---|---|---|
| ① | 외국인/기관 수급 성격 | 공매도 청산용(숏커버링) 단기 매수 | 2~3주 이상 지속되는 실질 신규 순매수 |
| ② | 거래량 패턴 | 하락 대비 반등 시 거래량 부족·단발성 | 바닥 손바꿈 후 상승 시 거래량 지속 증가 |
| ③ | 개인 vs 외국인·기관 수급 조합 | 개인 순매수 지속, 외국인·기관 매도 지속 | 외국인·기관 쌍끌이 순매수 |
| ④ | 해외(미국 빅테크) 동반 상승 | 국장 단독의 미미한 기술적 반등 | 미국 빅테크·글로벌 증시 동반 상승 |

> ※ 신용잔고(빚투) 지표는 무료 데이터 소스 한계로 자동 분석에는 포함되지 않았습니다.
> 개인 신용잔고가 높은 수준을 유지한 채 반등하면 데드캣 바운스 가능성이 높다는 점을 참고하세요.
            """
        )

    # ── 신호 계산 ────────────────────────────────────────────
    signals = [
        deadcat.signal_short_covering(shorting, investor),
        deadcat.signal_volume_pattern(price_volume, low_date),
        deadcat.signal_investor_combo(investor),
        deadcat.signal_global_correlation(close, us_series_map),
    ]
    conclusion = deadcat.conclude(signals, close)

    # ── 결론 박스 (항상 최상단) ──────────────────────────────
    verdict_color = {
        "dead_cat_likely": "#ff4d4f",
        "real_rebound_likely": "#2ecc71",
        "inconclusive": "#8892b0",
    }[conclusion["verdict"]]

    chg_str = ""
    if conclusion["change_pct"] is not None:
        chg_str = f" ({conclusion['change_pct']:+.2f}%)"

    st.markdown(
        f"""
<div style="border:2px solid {verdict_color}; border-radius:10px; padding:16px 20px; margin-bottom:16px;">
  <div style="font-size:0.85em; opacity:0.7;">{name} ({ticker}) · 기준일 {conclusion['as_of'] or '-'} 종가 {conclusion['last_close']:,.0f}원{chg_str}</div>
  <div style="font-size:1.3em; font-weight:700; color:{verdict_color}; margin:6px 0;">
    결론: {conclusion['verdict_label']}
  </div>
  <div style="font-size:0.9em; opacity:0.85;">
    데드캣 신호 {conclusion['dead_cat_score']}개 · 진짜반등 신호 {conclusion['real_rebound_score']}개
    · 데이터없음 {conclusion['unknown_count']}개
  </div>
</div>
        """,
        unsafe_allow_html=True,
    )

    st.subheader("근거")
    for r in conclusion["reasons"]:
        st.markdown(f"- {r}")

    st.markdown("---")

    # ── 신호별 카드 ──────────────────────────────────────────
    st.subheader("판별 지표별 상세")
    cols = st.columns(4)
    for i, sig in enumerate(signals):
        label_str, color = LABEL_STYLE[sig["label"]]
        with cols[i]:
            st.markdown(
                f"""<div style="border-left:4px solid {color}; padding:8px 12px; background:rgba(128,128,128,0.06); border-radius:4px; min-height:150px;">
                <b>{sig['title']}</b><br>
                <span style="color:{color}; font-weight:600;">{label_str}</span>
                <p style="font-size:0.82em; margin-top:6px;">{sig['reason']}</p>
                </div>""",
                unsafe_allow_html=True,
            )

    st.markdown("---")

    # ── 공매도 · 투자자별 수급 ─────────────────────────────────
    if not shorting.empty:
        st.subheader("공매도 거래비중 · 잔고비중")
        st.plotly_chart(shorting_chart(shorting, dark=dark), use_container_width=True)
    else:
        st.info("공매도 데이터 없음 (KRX 로그인 필요)")

    if not investor.empty:
        st.subheader("투자자별(외국인/기관/개인) 순매수 대금")
        st.plotly_chart(investor_flow_chart(investor, dark=dark), use_container_width=True)
    else:
        st.info("투자자별 수급 데이터 없음 (KRX 로그인 필요)")

    if us_series_map:
        st.subheader("글로벌 주도주 동반 상승 비교 (정규화, 첫날=100)")
        from stockindex.dashboard.components.charts import line_chart
        compare_map = {"kr": close.rename("kr"), **us_series_map}
        compare_names = {"kr": name, **{k: k for k in us_series_map}}
        st.plotly_chart(
            line_chart(compare_map, compare_names, title="", normalize=True, dark=dark),
            use_container_width=True,
        )

    st.caption(
        "데이터 출처: [KRX 정보데이터시스템](https://data.krx.co.kr) (pykrx). "
        "본 분석은 투자 조언이 아니며 참고용입니다."
    )
