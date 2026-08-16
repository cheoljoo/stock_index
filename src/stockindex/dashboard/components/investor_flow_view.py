""""외국인·기관 수급 스크리너" 페이지 — KOSPI200 중 수급이 몰리는/빠지는 종목을 한눈에 본다.

`app.py`의 사이드바 메뉴가 "🦅 외국인·기관 수급 스크리너"일 때 `render()`가 호출된다.
매일 cron(`run_daily.py`)이 `core/screener.screen_kospi200()`으로 계산해 저장한 최신
스냅샷(`investor_flow_screen` 테이블)만 읽는다 — 이 페이지 자체는 KRX를 실시간 조회하지
않으므로, 화면에 보이는 값은 마지막 cron 실행 시점 기준이다.

```mermaid
flowchart TD
    A["storage.db.get_latest_investor_flow_screen()"] --> B["필터: 동반매수/동반매도/외국인단독매수 + 최소 연속일수"]
    B --> C["표: 종목명·연속일수·현재가"]
    C --> D["종목 선택 시 investor_flow_chart로 드릴다운 (KRX 실시간, 30분 캐시)"]

    E["storage.db.get_latest_ownership_screen()"] --> F["필터: 지속증가/일시급증"]
    F --> G["표: 종목명·지분율변화·현재지분율"]
    G --> H["종목 선택 시 지분율 추이 line_chart로 드릴다운"]
```

아래 두 섹션은 서로 완전히 독립적인 스크리너다: 위쪽("연속 매수/매도")은 거래 **횟수**(며칠
연속 같은 방향으로 순매수했는지)를 보고, 아래쪽("지분율 변화")은 실제 **보유 비중** 자체가
얼마나 늘었는지를 본다. 순매수가 반복돼도 유상증자로 상장주식수가 같이 늘면 지분율은
그대로일 수 있어 두 지표가 항상 같은 방향을 가리키지는 않는다.

**주의**: 예전엔 이 페이지에 "지금 다시 스캔" 버튼을 넣어 `screen_kospi200()`을 웹에서 직접
실행했으나, 여러 종목을 연달아 빠르게 KRX에 실시간 조회하는 패턴이 streamlit 프로세스를
세그폴트(SIGSEGV)로 죽이는 것을 확인해 제거했다(대시보드 전체가 같이 죽는 문제라 위험도가
너무 컸다). 즉시 갱신이 필요하면 `scripts/run_screener.py`를 **터미널에서 별도 프로세스로**
실행할 것 — 그 프로세스만 죽어도 대시보드는 영향받지 않는다.
"""
from __future__ import annotations
from datetime import date, timedelta
import pandas as pd
import streamlit as st

from stockindex.config.loader import load_settings
from stockindex.providers import krx_provider as krx
from stockindex.storage import db as _db
from stockindex.dashboard.components.charts import investor_flow_chart, line_chart

_FILTER_COLS = {
    "전체": None,
    "동반매수만": "twin_buy_streak",
    "동반매도만": "twin_sell_streak",
    "외국인단독매수만": "foreign_only_buy_streak",
}

_OWNERSHIP_FILTERS = {
    "전체": None,
    "지속 증가만": "is_steady_increase",
    "일시 급증만": "is_spike",
}


@st.cache_data(ttl=1800)
def _load_drilldown(ticker: str, start: date, end: date):
    return krx.get_investor_trading(ticker, start, end)


@st.cache_data(ttl=1800)
def _load_ownership_drilldown(ticker: str, start: date, end: date):
    return krx.get_foreign_ownership(ticker, start, end)


def render(dark: bool) -> None:
    print("[investor_flow_view] render() 시작")
    st.title("🦅 외국인·기관 수급 스크리너")
    st.caption(
        "KOSPI200 종목 중 외국인·기관이 며칠째 같은 방향으로 사거나(동반매수) 팔고 있는지(동반매도), "
        "또는 외국인만 사고 있는지를 매일 스캔한 결과입니다."
    )

    if not krx.krx_authenticated():
        print("[investor_flow_view] KRX 미인증 — 여기서 종료")
        st.error(
            "⚠️ KRX_ID/KRX_PW가 설정되지 않았거나 로그인에 실패한 상태입니다. "
            "이 페이지는 투자자별(외국인/기관) 수급 데이터가 필요해 **KRX 로그인 없이는 동작하지 않습니다**.\n\n"
            "data.krx.co.kr에서 로그인해 비밀번호를 갱신한 뒤 `.env`의 `KRX_PW`를 업데이트하세요."
        )
        return

    settings = load_settings()
    db_path = settings.storage.db_path
    print(f"[investor_flow_view] db_path={db_path}")

    st.caption(
        "💡 즉시 갱신하려면 대시보드가 아니라 터미널에서 "
        "`.venv/bin/python scripts/run_screener.py` 를 실행하세요 "
        "(대시보드 안에서 직접 스캔을 돌리면 프로세스가 죽는 문제가 있어 뺐습니다)."
    )

    rows = _db.get_latest_investor_flow_screen(db_path)
    print(f"[investor_flow_view] rows={len(rows)}")
    if not rows:
        st.info(
            "아직 저장된 스크리너 결과가 없습니다. 터미널에서 `scripts/run_screener.py` "
            "또는 `scripts/run_daily.py`를 최소 한 번 실행해야(cron 04:00 또는 수동 실행) "
            "이 화면에 데이터가 채워집니다."
        )
        return

    df = pd.DataFrame(rows)
    snapshot_date = df["snapshot_date"].iloc[0]
    st.caption(f"📅 스냅샷 기준일: {snapshot_date}")

    run_meta = _db.get_latest_screen_run(db_path)
    if run_meta and not run_meta.get("is_full_kospi200"):
        st.warning(
            f"⚠️ KOSPI200 정식 구성종목 API(pykrx)가 현재 KRX 쪽 변경으로 조회되지 않아, "
            f"**대형주 근사 리스트({run_meta.get('universe_size')}종목)**만 스캔한 결과입니다. "
            "KOSPI200 전 종목이 아님에 유의하세요.",
            icon="⚠️",
        )

    col1, col2 = st.columns([2, 1])
    with col1:
        filter_label = st.radio("필터", list(_FILTER_COLS.keys()), horizontal=True)
    with col2:
        min_days = st.number_input("최소 연속일수", min_value=1, max_value=30, value=1, step=1)

    col_name = _FILTER_COLS[filter_label]
    streak_cols = ["twin_buy_streak", "twin_sell_streak", "foreign_only_buy_streak"]
    if col_name is None:
        mask = df[streak_cols].max(axis=1) >= min_days
        sort_col = df[streak_cols].max(axis=1)
        filtered = df[mask].assign(_정렬용=sort_col[mask]).sort_values("_정렬용", ascending=False).drop(columns="_정렬용")
    else:
        filtered = df[df[col_name] >= min_days].sort_values(col_name, ascending=False)

    if filtered.empty:
        st.info(f"'{filter_label}' 조건({min_days}일 이상)을 만족하는 종목이 없습니다. "
                f"(전체 스캔 대상 {len(df)}종목 중 저장된 스냅샷은 최소 1개 이상 연속일수를 만족하는 종목만 담겨 있습니다.)")
        return

    display_cols = ["ticker", "name"] + (streak_cols if col_name is None else [col_name]) + ["latest_close"]
    rename_map = {
        "ticker": "코드", "name": "종목명", "latest_close": "현재가",
        "twin_buy_streak": "동반매수", "twin_sell_streak": "동반매도", "foreign_only_buy_streak": "외국인단독매수",
    }
    display_df = filtered[display_cols].rename(columns=rename_map).copy()
    # pandas Styler를 st.dataframe에 그대로 넘기면 일부 환경에서 Arrow 변환이 깨져
    # 화면에 아무것도 안 그려지는 경우가 있어(콘솔 에러도 없음), Styler 대신 값 자체를
    # 표시용 문자열로 미리 바꿔서 넘긴다.
    display_df["현재가"] = display_df["현재가"].map(
        lambda v: f"{v:,.0f}" if pd.notna(v) else "-"
    )
    print(f"[investor_flow_view] display_df {len(display_df)}행 렌더 완료")
    st.dataframe(display_df, width="stretch", hide_index=True)

    st.markdown("---")
    st.subheader("종목 상세 (수급 차트)")
    options = {f"{r['name']} ({r['ticker']})": r["ticker"] for _, r in filtered.iterrows()}
    picked = st.selectbox("종목 선택", list(options.keys()))
    if picked:
        ticker = options[picked]
        end = date.today()
        start = end - timedelta(days=60)
        investor = _load_drilldown(ticker, start, end)
        if investor.empty:
            st.warning("투자자별 수급 데이터를 불러오지 못했습니다.")
        else:
            st.plotly_chart(
                investor_flow_chart(investor, title=f"{picked} 투자자별 순매수 대금 (최근 60일)", dark=dark),
                width="stretch",
            )

    _render_ownership_section(db_path, dark)


def _render_ownership_section(db_path: str, dark: bool) -> None:
    """외국인 지분율(보유 비중) 지속증가/일시급증 스크리너 섹션."""
    print("[investor_flow_view] ownership 섹션 시작")
    st.markdown("---")
    st.header("📈 외국인 지분율 변화")
    st.caption(
        "며칠 연속 순매수했는지가 아니라, **실제 외국인 보유 지분율 자체**가 꾸준히 늘고 있는지(지속 증가) "
        "또는 특정 하루에 크게 늘었는지(일시 급증)를 봅니다."
    )

    own_rows = _db.get_latest_ownership_screen(db_path)
    print(f"[investor_flow_view] ownership rows={len(own_rows)}")
    if not own_rows:
        st.info(
            "아직 저장된 지분율 스크리너 결과가 없습니다. 터미널에서 `scripts/run_screener.py` "
            "또는 `scripts/run_daily.py`를 최소 한 번 실행해야 이 화면에 데이터가 채워집니다."
        )
        return

    own_df = pd.DataFrame(own_rows)
    own_snapshot = own_df["snapshot_date"].iloc[0]
    st.caption(f"📅 스냅샷 기준일: {own_snapshot}")

    own_run_meta = _db.get_latest_ownership_screen_run(db_path)
    if own_run_meta and not own_run_meta.get("is_full_kospi200"):
        st.warning(
            f"⚠️ KOSPI200 정식 구성종목 API가 조회되지 않아 대형주 근사 리스트"
            f"({own_run_meta.get('universe_size')}종목)만 스캔한 결과입니다.",
            icon="⚠️",
        )

    own_filter_label = st.radio("지분율 필터", list(_OWNERSHIP_FILTERS.keys()), horizontal=True, key="ownership_filter")
    own_col = _OWNERSHIP_FILTERS[own_filter_label]
    if own_col is None:
        own_filtered = own_df.sort_values("change_pct_points", ascending=False)
    else:
        own_filtered = own_df[own_df[own_col] == 1].sort_values("change_pct_points", ascending=False)

    if own_filtered.empty:
        st.info(f"'{own_filter_label}' 조건을 만족하는 종목이 없습니다.")
        return

    own_display = own_filtered[[
        "ticker", "name", "change_pct_points", "up_day_ratio", "max_daily_jump",
        "is_steady_increase", "is_spike", "latest_ratio", "latest_close",
    ]].rename(columns={
        "ticker": "코드", "name": "종목명", "change_pct_points": "구간변화(%p)",
        "up_day_ratio": "상승일비율", "max_daily_jump": "최대일간상승(%p)",
        "is_steady_increase": "지속증가", "is_spike": "일시급증",
        "latest_ratio": "현재지분율(%)", "latest_close": "현재가",
    }).copy()
    own_display["지속증가"] = own_display["지속증가"].map({1: "✅", 0: ""})
    own_display["일시급증"] = own_display["일시급증"].map({1: "✅", 0: ""})
    own_display["상승일비율"] = own_display["상승일비율"].map(lambda v: f"{v:.0%}" if pd.notna(v) else "-")
    own_display["현재가"] = own_display["현재가"].map(lambda v: f"{v:,.0f}" if pd.notna(v) else "-")
    print(f"[investor_flow_view] ownership display {len(own_display)}행 렌더 완료")
    st.dataframe(own_display, width="stretch", hide_index=True)

    st.markdown("---")
    st.subheader("종목 상세 (지분율 추이)")
    own_options = {f"{r['name']} ({r['ticker']})": r["ticker"] for _, r in own_filtered.iterrows()}
    own_picked = st.selectbox("종목 선택", list(own_options.keys()), key="ownership_ticker_select")
    if own_picked:
        ticker = own_options[own_picked]
        end = date.today()
        start = end - timedelta(days=60)
        ownership = _load_ownership_drilldown(ticker, start, end)
        if ownership.empty or "foreign_ratio" not in ownership.columns:
            st.warning("외국인 지분율 데이터를 불러오지 못했습니다.")
        else:
            st.plotly_chart(
                line_chart(
                    {"foreign_ratio": ownership["foreign_ratio"]},
                    {"foreign_ratio": f"{own_picked} 외국인 지분율(%)"},
                    title=f"{own_picked} 외국인 지분율 추이 (최근 60일)",
                    markers=True, dark=dark,
                ),
                width="stretch",
            )
