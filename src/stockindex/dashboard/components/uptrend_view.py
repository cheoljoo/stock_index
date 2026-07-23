""""상승 추세 전환 분석" 페이지 — 종목 하나를 골라 7가지 대칭(상승/하락) 신호로 추세를 판별한다.

`app.py`의 사이드바 메뉴가 "📈 상승 추세 전환 분석"일 때 `render()`가 호출된다.
`deadcat_view`와 마찬가지로 pykrx 실시간 조회(30분 캐시)이며, 저장된 일별 지표와는 무관하다.

```mermaid
flowchart TD
    A["사용자: 종목 선택 (PRESET_TICKERS 공유)"] --> B["_load_ticker_data (KRX 실시간 조회)"]
    B --> S1["golden_cross"] & S2["rsi"] & S3["macd"] & S4["higher_low_high"]
    B --> S5["box_breakout"] & S6["volume_spike"] & S7["investor_twin_buy"]
    S1 & S2 & S3 & S4 & S5 & S6 & S7 --> D["uptrend.conclude() — 상승/하락 신호 개수로 5단계 판정"]
    D --> E["결론 박스 + 근거 + 신호 카드 + RSI/MACD/거래량 차트"]
    E --> F["_render_summary_table — PRESET_TICKERS 전체 일괄 판정 요약표"]
```
"""
from __future__ import annotations
from datetime import date, timedelta
import pandas as pd
import streamlit as st

from stockindex.providers import krx_provider as krx
from stockindex.core import uptrend
from stockindex.dashboard.components.deadcat_view import PRESET_TICKERS
from stockindex.dashboard.components.charts import price_volume_chart, rsi_chart, macd_chart, investor_flow_chart

LABEL_STYLE = {
    "bullish": ("📈 상승 신호", "#2ecc71"),
    "bearish": ("📉 하락 신호", "#ff4d4f"),
    "neutral": ("➖ 중립", "#8892b0"),
    "unknown": ("❔ 데이터 없음", "#8892b0"),
}

VERDICT_COLOR = {
    "strong_uptrend": "#2ecc71",
    "building": "#8bd4a0",
    "neutral": "#8892b0",
    "weakening": "#f7a44f",
    "strong_downtrend": "#ff4d4f",
    "inconclusive": "#8892b0",
}

# 초등학생도 이해할 수 있는 쉬운 설명 (신호 key → 설명 문단)
KID_EXPLANATIONS = {
    "golden_cross": (
        "📏 **이평선 골든·데드크로스**\n\n"
        "'이동평균선'은 최근 며칠 동안의 **평균 주가**예요. 예를 들어 20일선은 최근 20일 동안의 평균 가격, "
        "60일선은 최근 60일 동안의 평균 가격이에요. **짧은 기간 평균(20일선)이 긴 기간 평균(60일선)보다 위로 올라가면**, "
        "요즘 가격이 예전보다 계속 오르고 있다는 뜻이라 좋은 신호(골든크로스)예요. 반대로 아래로 내려가면 "
        "안 좋은 신호(데드크로스)예요. 마치 최근 성적 평균이 예전 성적 평균보다 좋아지고 있는지 보는 것과 비슷해요."
    ),
    "rsi": (
        "🌡️ **RSI 50선 돌파**\n\n"
        "RSI는 '요즘 사려는 사람이 많은지, 팔려는 사람이 많은지'를 0~100 사이 숫자로 나타낸 온도계 같은 거예요. "
        "50보다 크면 **사자는 힘이 더 세다**는 뜻이고, 50보다 작으면 **팔자는 힘이 더 세다**는 뜻이에요. "
        "숫자가 30 밑으로 떨어졌다가(너무 많이 팔려서 쌌음) 다시 50을 넘으면, 팔려던 사람들이 지치고 "
        "사려는 사람들이 이기기 시작했다는 신호예요."
    ),
    "macd": (
        "🚗 **MACD 시그널·기준선 돌파**\n\n"
        "MACD는 '최근 흐름'과 '조금 더 오래된 흐름'의 차이를 보여주는 선이에요. "
        "이 선이 자기보다 천천히 움직이는 '시그널선'을 위로 넘으면, 최근 흐름이 **점점 빨라지고 있다**(가속 페달을 밟는 중)는 뜻이에요. "
        "기준선(0)을 넘으면 아예 흐름 자체가 상승 쪽으로 완전히 바뀐 거예요."
    ),
    "higher_low_high": (
        "🪜 **가격 파동 패턴(N자/역N자)**\n\n"
        "주가는 오르고 내리기를 반복하면서 물결처럼 움직여요. 이번에 내려간 저점이 **저번 저점보다 덜 떨어지고**, "
        "그다음 올라간 고점이 **저번 고점보다 더 높이 올라가면**, 마치 계단을 한 칸씩 올라가는 모양이라서 "
        "진짜 상승 추세로 봐요(N자 모양). 반대로 자꾸 저번보다 더 낮게 떨어지면 계단을 내려가는 모양(역N자)이에요."
    ),
    "box_breakout": (
        "🚪 **박스권 저항선/지지선**\n\n"
        "주가가 오랫동안 어떤 가격을 넘지 못하고 있으면, 그 가격을 '천장(저항선)'이라고 불러요. "
        "이 천장을 뚫고 올라가면, 갇혀 있던 방에서 문을 열고 나온 것처럼 **앞으로 더 오를 힘**이 생겼다는 뜻이에요. "
        "반대로 오랫동안 버티던 바닥(지지선)이 뚫리면, 마루가 꺼진 것처럼 **더 떨어질 수 있다**는 뜻이에요."
    ),
    "volume_spike": (
        "📢 **거래량 급증 동반 캔들**\n\n"
        "거래량이 평소보다 2.5배 넘게 갑자기 많아졌다는 건, 오늘 이 주식에 정말 많은 사람이 관심을 가졌다는 뜻이에요. "
        "이때 가격이 올라서 끝났으면(양봉) '많은 사람이 몰려서 힘차게 밀어올렸다'는 좋은 신호이고, "
        "반대로 가격이 떨어져서 끝났으면(음봉) '다들 놀라서 던지듯이 팔았다'는 안 좋은 신호예요."
    ),
    "investor_twin_buy": (
        "🤝 **외국인·기관 쌍끌이 매매**\n\n"
        "외국인과 기관(전문 투자자들)이 **3일 넘게 계속 같이 사들이면**, 전문가들이 여러 날에 걸쳐 꾸준히 믿고 사는 거라서 "
        "믿을 만한 상승 신호예요. 반대로 며칠 동안 계속 같이 팔면, 전문가들이 등을 돌리고 있다는 뜻이라 조심해야 해요."
    ),
}

# 5단계 결론(verdict)을 초등학생도 이해하도록 풀어쓴 설명
KID_VERDICT_EXPLANATION = """
### 🚦 결론에 나오는 5단계는 뭘까요?

위 7가지 지표 중에서 "상승 신호"가 몇 개 나왔는지, "하락 신호"가 몇 개 나왔는지 세어서 아래 5단계 중 하나로 알려드려요.
7명의 친구에게 "이 주식 오를 것 같아, 내릴 것 같아?"라고 물어봐서 손을 든 숫자를 세는 것과 비슷해요.

| 신호등 | 단계 이름 | 무슨 뜻일까요? |
|---|---|---|
| 🟢🟢 | **상승 추세 전환 신호 강함** | 7명 중 **5명 이상**이 "오를 것 같아!"라고 손을 들었어요. 정말 많은 친구가 같은 생각이라 믿을 만해요. |
| 🟢 | **상승 초입(모멘텀 형성 중)** | "오를 것 같아" 손든 친구가 "내릴 것 같아" 손든 친구보다 많아요. 아직 확실하진 않지만 **오르는 쪽으로 기울고 있어요.** |
| ⚪ | **방향성 불명확** | 손든 친구 수가 비슷하거나, 다들 "잘 모르겠어"라고 했어요. **아직은 어느 쪽인지 판단하기 어려워요.** |
| 🟠 | **하락 초입 또는 진행 중** | "내릴 것 같아" 손든 친구가 "오를 것 같아" 손든 친구보다 많아요. **떨어지는 쪽으로 기울고 있으니 조심하세요.** |
| 🔴🔴 | **하락 추세 진행 신호 강함** | 7명 중 **5명 이상**이 "내릴 것 같아!"라고 손을 들었어요. 정말 많은 친구가 같은 생각이라 **위험 신호**예요. |

> 참고로 KRX 로그인이 안 되어 있으면 "외국인·기관 쌍끌이 매매" 지표는 데이터가 없어서 손을 든 친구 수(7명)에서 빠지고 6명 기준으로 계산돼요.
"""


@st.cache_data(ttl=1800)
def _check_krx_login():
    """KRX 로그인 성공 여부를 30분 캐시한다."""
    return krx.check_krx_login()


@st.cache_data(ttl=1800)
def _load_ticker_data(ticker: str, start: date, end: date):
    """한 종목의 시세/투자자수급/종목명을 KRX에서 조회한다 (30분 캐시)."""
    price_volume = krx.get_price_volume(ticker, start, end)
    investor = krx.get_investor_trading(ticker, start, end)
    name = krx.get_stock_name(ticker)
    return price_volume, investor, name


def render(dark: bool) -> None:
    """상승 추세 전환 분석 페이지 전체를 그린다.

    Args:
        dark: 다크 테마 여부 (차트 색상 결정).
    """
    st.title("📈 상승 추세 전환 분석")
    st.caption(
        "\"떨어지는 칼날을 잡지 말고, 오르기 시작할 때 사라\" — "
        "이동평균선·RSI·MACD·가격패턴·거래량·수급 7가지 기준으로 "
        "**상승 추세로의 전환(추세 재개)** 신호를 점검합니다."
    )

    if not krx.krx_authenticated():
        st.warning(
            "외국인·기관 쌍끌이 매수 신호는 **KRX(data.krx.co.kr) 무료 회원 로그인**이 필요합니다.  \n"
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
                "로그인 실패 시 외국인·기관 수급 데이터는 표시되지 않습니다.",
                icon="🚫",
            )

    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        preset = st.selectbox(
            "종목 선택",
            list(PRESET_TICKERS.keys()),
            format_func=lambda t: f"{PRESET_TICKERS[t]} ({t})",
            key="uptrend_ticker_preset",
        )
    with col2:
        custom = st.text_input("직접 입력 (6자리 종목코드)", value="", key="uptrend_ticker_custom")
    with col3:
        days_back = st.number_input(
            "조회 기간(일)", min_value=120, max_value=400, value=200, step=20, key="uptrend_days_back",
        )

    ticker = custom.strip() if custom.strip() else preset
    end = date.today()
    start = end - timedelta(days=int(days_back))

    with st.spinner(f"{ticker} 데이터 조회 중..."):
        try:
            price_volume, investor, name = _load_ticker_data(ticker, start, end)
        except Exception as e:
            st.error(f"데이터 조회 실패: {e}")
            return

    if price_volume.empty:
        st.error(f"'{ticker}' 종목의 시세 데이터를 찾을 수 없습니다. 종목코드를 확인해주세요.")
        return

    close = price_volume["종가"]

    # ── 차트 (주가·거래량·이평선, 최상단) ──────────────────────
    st.subheader("주가 · 거래량 (5/20/60/120일 이평선)")
    st.plotly_chart(
        price_volume_chart(
            close, price_volume["거래량"], title=f"{name} 종가·거래량", dark=dark,
            ma_windows=(5, 20, 60, 120),
        ),
        use_container_width=True,
    )
    st.markdown("---")

    # ── 지표 설명 ────────────────────────────────────────────
    with st.expander("📖 판별 지표 설명 (7가지 기준, 상승/하락 대칭 판별)", expanded=False):
        st.markdown(
            """
| # | 지표 | 📈 상승 신호 | 📉 하락 신호 |
|---|---|---|---|
| ① | 이평선 골든·데드크로스 | 단기선(20일)이 장기선(60일)을 상향 돌파·정배열 | 단기선이 장기선을 하향 돌파·역배열 |
| ② | RSI 50선 돌파 | 과매도(30 이하) 이후 중립선(50) 상향 돌파 | 과매수(70 이상) 이후 중립선(50) 하향 돌파 |
| ③ | MACD 시그널·기준선 돌파 | MACD가 시그널선·기준선(0)을 상향 돌파 | MACD가 시그널선·기준선(0)을 하향 돌파 |
| ④ | 가격 파동 패턴(다우 이론) | N자형: Higher-Low 후 Higher-High | 역N자형: Lower-High 후 Lower-Low |
| ⑤ | 박스권 저항선/지지선 | 최근 60거래일 저항선(최고가) 상향 돌파 | 최근 60거래일 지지선(최저가) 하향 이탈 |
| ⑥ | 거래량 급증 동반 캔들 | 20일 평균 2.5배 이상 거래량 + 양봉 | 20일 평균 2.5배 이상 거래량 + 음봉(투매) |
| ⑦ | 외국인·기관 쌍끌이 매매 | 3거래일 이상 연속 동시 순매수 | 3거래일 이상 연속 동시 순매도 |

**결론 판정 기준** (7개 지표 중 데이터가 있는 지표 기준)
- 🟢 **상승 추세 전환 강함**: 상승 신호 5개 이상
- 🟢 **상승 초입(모멘텀 형성 중)**: 상승 신호가 하락보다 많고, 유효 지표의 40% 이상
- ⚪ **방향성 불명확**: 신호가 뒤섞이거나 40% 기준에 못 미침
- 🟠 **하락 초입/진행 중**: 하락 신호가 상승보다 많고, 유효 지표의 40% 이상
- 🔴 **하락 추세 진행 강함**: 하락 신호 5개 이상
            """
        )

    # ── 신호 계산 ────────────────────────────────────────────
    signals = [
        uptrend.signal_golden_cross(close),
        uptrend.signal_rsi(close),
        uptrend.signal_macd(close),
        uptrend.signal_higher_low_high(close),
        uptrend.signal_box_breakout(price_volume),
        uptrend.signal_volume_spike(price_volume),
        uptrend.signal_investor_twin_buy(investor),
    ]
    conclusion = uptrend.conclude(signals, close)

    # ── 결론 박스 (항상 최상단) ──────────────────────────────
    verdict_color = VERDICT_COLOR[conclusion["verdict"]]
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
    상승 {conclusion['bullish_count']}개 · 하락 {conclusion['bearish_count']}개 · 중립 {conclusion['neutral_count']}개
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
        with cols[i % 4]:
            st.markdown(
                f"""<div style="border-left:4px solid {color}; padding:8px 12px; background:rgba(128,128,128,0.06); border-radius:4px; min-height:150px; margin-bottom:12px;">
                <b>{sig['title']}</b><br>
                <span style="color:{color}; font-weight:600;">{label_str}</span>
                <p style="font-size:0.82em; margin-top:6px;">{sig['reason']}</p>
                </div>""",
                unsafe_allow_html=True,
            )

    with st.expander("🧒 쉽게 설명해드릴게요! (지표별 쉬운 풀이)", expanded=False):
        st.markdown(KID_VERDICT_EXPLANATION)
        st.markdown("---")
        for sig in signals:
            explain = KID_EXPLANATIONS.get(sig["key"])
            if explain:
                st.markdown(explain)
                st.markdown("")

    st.markdown("---")

    # ── RSI · MACD 차트 ─────────────────────────────────────
    st.subheader("RSI(14)")
    st.plotly_chart(rsi_chart(uptrend.rsi(close), dark=dark), use_container_width=True)

    st.subheader("MACD")
    macd_line, signal_line, hist = uptrend.macd(close)
    st.plotly_chart(macd_chart(macd_line, signal_line, hist, dark=dark), use_container_width=True)

    if not investor.empty:
        st.subheader("투자자별(외국인/기관/개인) 순매수 대금")
        st.plotly_chart(investor_flow_chart(investor, dark=dark), use_container_width=True)
    else:
        st.info("투자자별 수급 데이터 없음 (KRX 로그인 필요)")

    st.caption(
        "데이터 출처: [KRX 정보데이터시스템](https://data.krx.co.kr) (pykrx). "
        "본 분석은 투자 조언이 아니며 참고용입니다."
    )

    _render_summary_table()


@st.cache_data(ttl=1800)
def _summary_rows(tickers: dict[str, str], start: date, end: date) -> list[dict]:
    """`tickers`의 각 종목에 대해 7가지 신호를 계산해 요약표 행(dict)으로 만든다 (30분 캐시)."""
    rows = []
    for ticker, tname in tickers.items():
        try:
            price_volume, investor, _ = _load_ticker_data(ticker, start, end)
        except Exception:
            continue
        if price_volume.empty:
            continue
        close = price_volume["종가"]
        signals = [
            uptrend.signal_golden_cross(close),
            uptrend.signal_rsi(close),
            uptrend.signal_macd(close),
            uptrend.signal_higher_low_high(close),
            uptrend.signal_box_breakout(price_volume),
            uptrend.signal_volume_spike(price_volume),
            uptrend.signal_investor_twin_buy(investor),
        ]
        concl = uptrend.conclude(signals, close)
        rows.append({
            "종목": tname, "코드": ticker,
            "결론": concl["verdict_label"],
            "상승 신호": concl["bullish_count"],
            "하락 신호": concl["bearish_count"],
            "중립": concl["neutral_count"],
            "데이터없음": concl["unknown_count"],
            "종가": concl["last_close"],
            "등락률(%)": round(concl["change_pct"], 2) if concl["change_pct"] is not None else None,
        })
    return rows


def _render_summary_table() -> None:
    """페이지 맨 아래에 `PRESET_TICKERS` 전체 종목의 상승/하락 판정 요약표를 그린다."""
    st.markdown("---")
    st.subheader("📋 선택 가능 종목 요약")
    st.caption("아래 종목들에 대해 동일한 7가지 기준으로 일괄 계산한 요약입니다. (최근 200일 기준)")
    end = date.today()
    start = end - timedelta(days=200)
    with st.spinner("전체 종목 요약 계산 중..."):
        rows = _summary_rows(PRESET_TICKERS, start, end)
    if not rows:
        st.info("요약할 데이터가 없습니다.")
        return
    df = pd.DataFrame(rows).sort_values("상승 신호", ascending=False)
    st.dataframe(df, use_container_width=True, hide_index=True)
