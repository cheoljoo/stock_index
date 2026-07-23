""""데드캣 바운스 분석" 페이지 — 종목 하나를 골라 반등이 일시적인지 추세 전환인지 판별한다.

`app.py`의 사이드바 메뉴가 "🐈‍⬛ 데드캣 바운스 분석"일 때 `render()`가 호출된다.
데이터는 매일 수집되는 지표(Parquet)와 무관하게, 페이지를 열 때마다 pykrx로
**실시간 조회**한다(캐시 30분).

```mermaid
flowchart TD
    A["사용자: 종목 선택 (PRESET_TICKERS 또는 직접입력)"] --> B["_load_ticker_data (KRX 실시간 조회, 30분 캐시)"]
    B --> C1["signal_short_covering"]
    B --> C2["signal_volume_pattern"]
    B --> C3["signal_investor_combo"]
    B --> C4["signal_global_correlation (us_series_map과 비교)"]
    C1 & C2 & C3 & C4 --> D["deadcat.conclude() — 데드캣 vs 진짜반등 점수 집계"]
    D --> E["결론 박스 + 근거 + 신호 카드 + 차트 렌더"]
    E --> F["_render_summary_table — PRESET_TICKERS 전체를 일괄 계산해 요약표 표시"]
```
"""
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
    "005930": "삼성전자", "005935": "삼성전자우", "000660": "SK하이닉스", "373220": "LG에너지솔루션",
    "207940": "삼성바이오로직스", "005380": "현대차", "005490": "POSCO홀딩스",
    "035420": "NAVER", "035720": "카카오", "051910": "LG화학", "006400": "삼성SDI",
    "000270": "기아", "068270": "셀트리온", "105560": "KB금융", "055550": "신한지주",
    "352820": "하이브",
}

# 신호 카드 표시용: deadcat.SignalLabel → (배지 문구, 색상)
LABEL_STYLE = {
    "dead_cat": ("🔻 데드캣 신호", "#ff4d4f"),
    "real_rebound": ("✅ 진짜 반등 신호", "#2ecc71"),
    "neutral": ("➖ 중립", "#8892b0"),
    "unknown": ("❔ 데이터 없음", "#8892b0"),
}

# 초등학생도 이해할 수 있는 쉬운 설명 (신호 key → 설명 문단)
KID_EXPLANATIONS = {
    "short_covering": (
        "🐱 **공매도·숏커버링 여부**\n\n"
        "'공매도'는 주가가 떨어질 거라 예상한 사람이 남의 주식을 미리 빌려서 파는 거예요. "
        "그런데 주가가 반대로 오르기 시작하면, 이 사람들은 손해를 보기 전에 **빌린 주식을 서둘러 다시 사서 갚아야** 해요. "
        "이걸 '숏커버링'이라고 해요. 이건 회사가 진짜 좋아져서 사는 게 아니라 **빚을 갚으려고 급하게 사는 것**이라서, "
        "반등이 오래가지 못하고 금방 끝나는 경우가 많아요. 마치 빌린 돈을 갚으려고 잠깐 급하게 뛰어다니는 것과 비슷해요."
    ),
    "volume_pattern": (
        "📊 **거래량 패턴**\n\n"
        "'거래량'은 오늘 이 주식을 사고판 사람이 몇 명이나 되는지 세어본 숫자예요. "
        "진짜로 주가가 좋아져서 오르는 거라면, 사려는 사람이 **여러 날 동안 계속 많아야** 해요. "
        "그런데 반등한 첫날에만 거래량이 반짝 많고 그다음 날부터 확 줄어들면, "
        "사람들이 금방 관심을 잃었다는 뜻이라 **'반짝 반등'일 가능성이 높아요.**"
    ),
    "investor_combo": (
        "🧑‍🤝‍🧑 **투자자 수급 조합**\n\n"
        "주식을 사는 사람은 크게 3종류가 있어요: **외국인**, **기관**(큰 회사나 펀드), **개인**(우리 같은 보통 사람들). "
        "외국인과 기관이 **같이 사면(쌍끌이 매수)** 전문가들이 서로 믿고 사는 거라서 좋은 신호예요. "
        "그런데 **개인들만 혼자 사고 외국인·기관은 계속 팔면**, 전문가들은 안 믿는데 일반 사람들만 '오르겠지' 하고 사는 거라 "
        "위험한 신호일 수 있어요."
    ),
    "global_correlation": (
        "🌍 **글로벌 동조화**\n\n"
        "미국처럼 큰 나라의 주식시장(나스닥 등)이 우리나라와 **같이 오르면**, 전 세계적으로 좋은 소식이 있다는 뜻이라 "
        "우리나라 주가도 **진짜로 오를 가능성**이 커요. 그런데 미국은 가만히 있는데 우리나라 주가만 혼자 오르면, "
        "특별한 이유 없이 **잠깐 튀어 오른 것**일 수 있어요."
    ),
}


@st.cache_data(ttl=1800)
def _check_krx_login():
    """KRX 로그인 성공 여부를 30분 캐시해 페이지를 새로고침할 때마다 재로그인하지 않게 한다."""
    return krx.check_krx_login()


@st.cache_data(ttl=1800)
def _load_ticker_data(ticker: str, start: date, end: date):
    """한 종목의 시세/공매도/투자자수급/종목명을 KRX에서 조회한다 (30분 캐시)."""
    price_volume = krx.get_price_volume(ticker, start, end)
    shorting = krx.get_shorting(ticker, start, end)
    investor = krx.get_investor_trading(ticker, start, end)
    name = krx.get_stock_name(ticker)
    return price_volume, shorting, investor, name


def render(dark: bool, us_series_map: dict[str, pd.Series]) -> None:
    """데드캣 바운스 분석 페이지 전체를 그린다.

    Args:
        dark: 다크 테마 여부 (차트 색상 결정).
        us_series_map: 글로벌 동조화 신호에 쓸 미국 지수 시계열 ({표시명: pd.Series}).
    """
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

    with st.expander("🧒 쉽게 설명해드릴게요! (지표별 쉬운 풀이)", expanded=False):
        for sig in signals:
            explain = KID_EXPLANATIONS.get(sig["key"])
            if explain:
                st.markdown(explain)
                st.markdown("")

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

    _render_summary_table(us_series_map)


@st.cache_data(ttl=1800)
def _summary_rows(tickers: dict[str, str], start: date, end: date) -> list[dict]:
    """`tickers`의 각 종목에 대해 데드캣 판정을 계산해 요약표 행(dict)으로 만든다 (30분 캐시)."""
    rows = []
    for ticker, tname in tickers.items():
        try:
            price_volume, shorting, investor, _ = _load_ticker_data(ticker, start, end)
        except Exception:
            continue
        if price_volume.empty:
            continue
        close = price_volume["종가"]
        low_date, _ = deadcat.find_recent_low(close, lookback=40)
        signals = [
            deadcat.signal_short_covering(shorting, investor),
            deadcat.signal_volume_pattern(price_volume, low_date),
            deadcat.signal_investor_combo(investor),
        ]
        concl = deadcat.conclude(signals, close)
        rows.append({
            "종목": tname, "코드": ticker,
            "결론": concl["verdict_label"],
            "데드캣 신호": concl["dead_cat_score"],
            "진짜반등 신호": concl["real_rebound_score"],
            "데이터없음": concl["unknown_count"],
            "종가": concl["last_close"],
            "등락률(%)": round(concl["change_pct"], 2) if concl["change_pct"] is not None else None,
        })
    return rows


def _render_summary_table(us_series_map: dict[str, pd.Series]) -> None:
    """페이지 맨 아래에 `PRESET_TICKERS` 전체 종목의 데드캣 판정 요약표를 그린다."""
    st.markdown("---")
    st.subheader("📋 선택 가능 종목 요약")
    st.caption("아래 종목들에 대해 동일한 기준(공매도·거래량·투자자 수급)으로 일괄 계산한 요약입니다. (글로벌 동조화 지표 제외 · 최근 60일 기준)")
    end = date.today()
    start = end - timedelta(days=60)
    with st.spinner("전체 종목 요약 계산 중..."):
        rows = _summary_rows(PRESET_TICKERS, start, end)
    if not rows:
        st.info("요약할 데이터가 없습니다.")
        return
    df = pd.DataFrame(rows).sort_values("데드캣 신호", ascending=False)
    st.dataframe(df, use_container_width=True, hide_index=True)
