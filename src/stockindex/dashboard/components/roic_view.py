""""ROIC 분석" 페이지 — S&P500 대형주들의 투하자본이익률(ROIC)을 비교한다.

워런 버핏이 구글(Alphabet)을 매수하며 "ROIC 30% 이상 기업을 고른다"고 언급해 유명해진 지표를
S&P500 상위 시가총액 종목들에 대해 계산한다.

```mermaid
flowchart TD
    W["get_ticker_universe(): Wikipedia S&P500 목록(7일 캐시)\n실패 시 TOP_SP500_TICKERS(100개)로 대체"] --> A["사용자: 종목 수(N) 선택"]
    A --> B["universe[:N]"]
    B --> C{"_load_roic(ticker):\nParquet에 저장된 값이 최근(1년 이내)인가?"}
    C -->|Yes| D["Parquet에서 즉시 로드 (yfinance 호출 없음)"]
    C -->|No/없음| E["yfinance로 재조회"]
    E --> F["기존 Parquet과 병합 후 저장 (data/series/roic_<ticker>.parquet)"]
    D --> G["전체 종목 x 연도 ROIC 표"]
    F --> G
    G --> H["최근 ROIC ≥ 사용자 지정 기준(기본 20%) 종목만 필터"]
    H --> I["필터된 종목의 연도별 ROIC 추세 그래프"]
```

## 저장·갱신 전략

연간 재무제표는 1년에 한 번(회사별 회계연도 마감 후 1~2개월 뒤) 갱신되므로, 매번 yfinance를
호출할 필요가 없다. `storage/timeseries.py`(다른 지표들과 같은 Parquet 저장소, 키는
`roic_<ticker>`)에 계산 결과를 저장해두고, **저장된 값의 최신 연도가 1년 이내면 그대로 재사용**하고
그렇지 않을 때만 yfinance를 다시 호출해 병합·저장한다. 이렇게 하면:
  - 최초 실행 이후에는 대부분 Parquet만 읽으므로 N=100이어도 페이지 로딩이 빠르다.
  - yfinance가 제공하는 기간(4~5년)보다 오래된 과거 데이터도, 예전에 한 번 받아둔 값이라면
    Parquet에 계속 누적되어 남는다(반복 실행할수록 보유 이력이 길어짐).

## 계산 방법 · 데이터 한계

- **ROIC = NOPAT / Invested Capital**, NOPAT(세후 영업이익) = EBIT × (1 − 유효세율).
  `Invested Capital`은 yfinance 대차대조표가 제공하는 값을 그대로 사용한다.
- yfinance 무료 API는 연간 재무제표를 보통 **최근 4~5개년치만** 제공한다 (유료 API처럼 10년
  전체를 제공하지 않음). 이 페이지는 제공되는 만큼만 표시하고 "10년"이 아님을 명시한다.
- 은행·보험 등 금융 섹터는 EBIT/Invested Capital 개념이 실물기업과 달라 yfinance가 값을
  제공하지 않는 경우가 많다 — 이 경우 "데이터 없음"으로 표시된다 (ROIC는 통상 금융업에는
  적용하지 않는 지표이므로 자연스러운 제외다).
- 종목 목록은 Wikipedia의 "List of S&P 500 companies" 표를 실시간 조회해 공식 구성종목
  전체(약 503개, 클래스 주식 포함)를 가져온다 (7일 캐시). 조회에 실패하면(네트워크 차단 등)
  아래 큐레이션 리스트(`TOP_SP500_TICKERS`, 100개)로 자동 대체된다.
- 500개 전체를 처음 조회하면 yfinance 호출이 많아 수 분 걸릴 수 있다 — 이후에는 종목별로
  Parquet에 저장된 값을 재사용하므로(위 "저장·갱신 전략" 참고) 빠르다.
"""
from __future__ import annotations
from io import StringIO
import pandas as pd
import requests
import streamlit as st

from stockindex.config.loader import load_settings
from stockindex.providers import yfinance_provider as yfp
from stockindex.storage import timeseries as ts
from stockindex.dashboard.components.charts import line_chart

# 저장된 ROIC 값을 "최신"으로 볼 최대 나이(일) — 이보다 오래되면 yfinance를 다시 조회한다.
_FRESHNESS_DAYS = 300

# S&P500 공식 구성종목 목록(Wikipedia) — 실패 시 큐레이션 리스트로 대체
_SP500_WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"

# 버핏이 언급해 유명해진 벤치마크(30%)와, 그래프 필터 기본값(20%, 사용자가 조정 가능)은 다르다 —
# 30% 기준은 너무 엄격해 대부분의 우량기업도 걸러지므로, 기본 필터는 조금 더 완만하게 잡는다.
BUFFETT_ROIC_BENCHMARK = 30.0
DEFAULT_ROIC_THRESHOLD = 20.0

# 시가총액 상위 기준으로 직접 고른 S&P500 대형주 목록 (실시간 공식 구성종목 목록이 아닌 큐레이션 리스트).
# 섹터를 고르게 섞되 대체로 시가총액 순서를 따른다.
TOP_SP500_TICKERS: list[str] = [
    "NVDA", "AAPL", "MSFT", "GOOGL", "AMZN", "META", "AVGO", "BRK-B", "TSLA", "LLY",
    "JPM", "WMT", "V", "MA", "ORCL", "NFLX", "XOM", "COST", "PG", "JNJ",
    "HD", "BAC", "ABBV", "KO", "PLTR", "CVX", "TMUS", "MRK", "PEP", "ADBE",
    "CSCO", "CRM", "ACN", "LIN", "WFC", "MCD", "IBM", "ABT", "NOW", "GE",
    "PM", "TXN", "CAT", "ISRG", "DIS", "VZ", "AMD", "MS", "INTU", "GS",
    "RTX", "T", "UBER", "PFE", "AXP", "BKNG", "QCOM", "SPGI", "BLK", "UNH",
    "AMGN", "HON", "LOW", "SYK", "NEE", "COP", "PGR", "ETN", "BSX", "TJX",
    "VRTX", "SCHW", "C", "MU", "BX", "ADP", "MDT", "LMT", "GILD", "PANW",
    "ADI", "CB", "SBUX", "MMC", "PLD", "AMT", "DE", "KLAC", "SO", "REGN",
    "APH", "CI", "MO", "DUK", "WM", "ICE", "SHW", "TT", "CME", "LRCX",
]

# 티커 → 회사명(한글). 표·그래프에서 "AAPL" 대신 "애플(AAPL)"처럼 표시하는 데 쓴다.
TICKER_NAMES: dict[str, str] = {
    "NVDA": "엔비디아", "AAPL": "애플", "MSFT": "마이크로소프트", "GOOGL": "알파벳(구글)",
    "AMZN": "아마존", "META": "메타(페이스북)", "AVGO": "브로드컴", "BRK-B": "버크셔해서웨이",
    "TSLA": "테슬라", "LLY": "일라이릴리",
    "JPM": "JP모건체이스", "WMT": "월마트", "V": "비자", "MA": "마스터카드", "ORCL": "오라클",
    "NFLX": "넷플릭스", "XOM": "엑슨모빌", "COST": "코스트코", "PG": "P&G", "JNJ": "존슨앤드존슨",
    "HD": "홈디포", "BAC": "뱅크오브아메리카", "ABBV": "애브비", "KO": "코카콜라", "PLTR": "팔란티어",
    "CVX": "셰브런", "TMUS": "T모바일US", "MRK": "머크", "PEP": "펩시코", "ADBE": "어도비",
    "CSCO": "시스코", "CRM": "세일즈포스", "ACN": "액센츄어", "LIN": "린데", "WFC": "웰스파고",
    "MCD": "맥도날드", "IBM": "IBM", "ABT": "애보트", "NOW": "서비스나우", "GE": "GE에어로스페이스",
    "PM": "필립모리스", "TXN": "텍사스인스트루먼트", "CAT": "캐터필러", "ISRG": "인튜이티브서지컬",
    "DIS": "월트디즈니", "VZ": "버라이즌", "AMD": "AMD", "MS": "모건스탠리", "INTU": "인튜이트",
    "GS": "골드만삭스",
    "RTX": "RTX(레이시온)", "T": "AT&T", "UBER": "우버", "PFE": "화이자", "AXP": "아메리칸익스프레스",
    "BKNG": "부킹홀딩스", "QCOM": "퀄컴", "SPGI": "S&P글로벌", "BLK": "블랙록", "UNH": "유나이티드헬스",
    "AMGN": "암젠", "HON": "허니웰", "LOW": "로우스", "SYK": "스트라이커", "NEE": "넥스트에라에너지",
    "COP": "코노코필립스", "PGR": "프로그레시브", "ETN": "이튼", "BSX": "보스턴사이언티픽", "TJX": "TJX",
    "VRTX": "버텍스파마슈티컬", "SCHW": "찰스슈왑", "C": "씨티그룹", "MU": "마이크론", "BX": "블랙스톤",
    "ADP": "ADP", "MDT": "메드트로닉", "LMT": "록히드마틴", "GILD": "길리어드사이언스", "PANW": "팔로알토네트웍스",
    "ADI": "아날로그디바이스", "CB": "처브", "SBUX": "스타벅스", "MMC": "마쉬앤맥레넌", "PLD": "프로로지스",
    "AMT": "아메리칸타워", "DE": "존디어", "KLAC": "KLA", "SO": "서던컴퍼니", "REGN": "리제네론",
    "APH": "앰페놀", "CI": "시그나", "MO": "알트리아", "DUK": "듀크에너지", "WM": "웨이스트매니지먼트",
    "ICE": "인터콘티넨탈익스체인지", "SHW": "셔윈윌리엄스", "TT": "트레인테크놀로지스", "CME": "CME그룹",
    "LRCX": "램리서치",
}


@st.cache_data(ttl=7 * 86400)
def _fetch_sp500_constituents() -> dict[str, str]:
    """Wikipedia에서 S&P500 공식 구성종목 전체를 가져온다 (7일 캐시).

    Returns:
        {yfinance용 티커: 영문 회사명}. 실패하면 빈 dict (호출부에서 큐레이션 리스트로 대체).
    """
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; stock_index-dashboard/1.0)"}
        resp = requests.get(_SP500_WIKI_URL, headers=headers, timeout=15)
        resp.raise_for_status()
        df = pd.read_html(StringIO(resp.text))[0]
        result = {}
        for _, row in df.iterrows():
            ticker = str(row["Symbol"]).strip().replace(".", "-")  # BRK.B → BRK-B (yfinance 표기)
            result[ticker] = str(row["Security"]).strip()
        return result
    except Exception:
        return {}


def get_ticker_universe() -> tuple[list[str], dict[str, str], bool]:
    """조회 가능한 전체 종목 목록을 구한다.

    Returns:
        (티커 목록, {티커: 영문명}, wiki_ok) — wiki_ok=False면 Wikipedia 조회 실패로
        큐레이션 리스트(100개)만 사용 중이라는 뜻.
    """
    wiki = _fetch_sp500_constituents()
    if wiki:
        return list(wiki.keys()), wiki, True
    return list(TOP_SP500_TICKERS), {}, False


def _roic_storage_key(ticker: str) -> str:
    return f"roic_{ticker}"


def _is_fresh(series: pd.Series) -> bool:
    """저장된 값의 최신 연도가 `_FRESHNESS_DAYS` 이내인지 확인한다."""
    if series.empty:
        return False
    age_days = (pd.Timestamp.now().normalize() - series.index.max()).days
    return age_days < _FRESHNESS_DAYS


@st.cache_data(ttl=3600)
def _load_roic(ticker: str) -> pd.Series:
    """한 종목의 연도별 ROIC(%)를 구한다.

    먼저 로컬 Parquet(`data/series/roic_<ticker>.parquet`)에 저장된 값을 확인해,
    최신(1년 이내)이면 yfinance를 호출하지 않고 그대로 반환한다. 저장된 값이 없거나
    오래됐을 때만 yfinance로 재조회하고, 기존 값과 병합해 다시 저장한다 — 그래야 매번
    전체 종목을 다시 받아오지 않고, 부족한(오래된) 부분만 새로 받아온다.
    """
    settings = load_settings()
    parquet_dir = settings.storage.parquet_dir
    key = _roic_storage_key(ticker)

    cached = ts.load_series(parquet_dir, key)
    if _is_fresh(cached):
        return cached

    try:
        fresh = yfp.fetch_roic_series(ticker)
    except Exception:
        return cached  # 조회 실패 시 오래된 값이라도 있으면 그거라도 보여준다

    if fresh.empty:
        return cached

    ts.save_series(parquet_dir, key, fresh)  # 기존 저장분과 자동 병합(append-merge)됨
    return ts.load_series(parquet_dir, key)


def _label(ticker: str, wiki_names: dict[str, str] | None = None) -> str:
    """표·그래프 표시용 라벨: '애플(AAPL)'처럼 회사명과 티커를 함께 보여준다.

    한글명(`TICKER_NAMES`, 큐레이션 100개)을 우선 쓰고, 없으면 Wikipedia 영문명을,
    그것도 없으면 티커만 그대로 보여준다.
    """
    name = TICKER_NAMES.get(ticker) or (wiki_names or {}).get(ticker)
    return f"{name}({ticker})" if name else ticker


def render(dark: bool) -> None:
    """ROIC 분석 페이지 전체를 그린다."""
    st.title("🏆 ROIC 분석 (S&P500)")
    st.caption(
        "워런 버핏이 구글(Alphabet)을 평가하며 \"ROIC 30% 이상 기업을 고른다\"고 언급해 유명해진 지표를 "
        "S&P500 대형주들에 대해 계산합니다. **ROIC = 세후영업이익(NOPAT) ÷ 투하자본(Invested Capital)**"
    )
    with st.expander("📖 워런 버핏이 말한 'ROIC 30%' — 무슨 맥락인가요?", expanded=False):
        st.markdown(
            "버크셔 해서웨이가 알파벳(구글) 지분을 새로 매수한 사실이 2025년 공시로 알려지면서 화제가 됐습니다. "
            "버핏과 버크셔가 오랫동안 강조해온 투자 원칙을 이 사례에 적용해 언론·투자자들 사이에서 알려진 취지는 "
            "대략 다음과 같습니다 (아래는 원문 그대로의 인용이 아니라 일반적으로 알려진 논지의 요약입니다):\n\n"
            "- 버핏은 단순히 '이익이 많이 나는 회사'보다 **투입한 자본 대비 얼마나 효율적으로 이익을 내는지**를 "
            "훨씬 중요하게 봅니다. 아무리 이익 규모가 커도, 그만큼 많은 자본을 쏟아부어야 한다면 진짜 좋은 사업이라 "
            "보기 어렵다는 것입니다.\n"
            "- 이를 재는 지표가 **ROIC(투하자본이익률)** 입니다. 알파벳처럼 몇 년 연속 **ROIC 30%를 넘는 기업**은 "
            "'적은 자본으로도 압도적인 이익을 뽑아내는 구조', 즉 강력한 경제적 해자(moat)를 가진 극소수의 우량기업일 "
            "가능성이 높다는 뜻으로 받아들여집니다.\n"
            "- 이 페이지는 그 기준(ROIC 30%)을 실제로 S&P500 대형주들에 적용해보면 어떤 기업들이 해당하는지 "
            "직접 계산해서 보여줍니다."
        )
    universe, wiki_names, wiki_ok = get_ticker_universe()
    if wiki_ok:
        st.caption(f"✅ Wikipedia에서 S&P500 공식 구성종목 {len(universe)}개를 불러왔습니다.")
    else:
        st.warning(
            "⚠️ Wikipedia에서 S&P500 목록을 가져오지 못해(네트워크 문제 등), "
            f"시가총액 상위 큐레이션 리스트 {len(universe)}개만 제공됩니다.",
            icon="⚠️",
        )
    st.info(
        "ℹ️ **데이터 한계 안내**: yfinance 무료 재무제표는 보통 최근 4~5개년치만 제공되어 "
        "'10년 전체'는 아닙니다. 은행·보험 등 금융주는 ROIC 계산에 필요한 항목을 yfinance가 "
        "제공하지 않아 데이터 없음으로 표시될 수 있습니다.",
        icon="ℹ️",
    )

    n = st.number_input(
        "조회할 종목 수",
        min_value=10, max_value=len(universe), value=min(30, len(universe)), step=10,
    )
    tickers = universe[: int(n)]

    roic_map: dict[str, pd.Series] = {}
    progress = st.progress(0.0, text=f"0/{len(tickers)}개 종목 ROIC 계산 중...")
    for i, t in enumerate(tickers, start=1):
        s = _load_roic(t)
        if not s.empty:
            roic_map[t] = s
        progress.progress(i / len(tickers), text=f"{i}/{len(tickers)}개 종목 ROIC 계산 중... ({_label(t, wiki_names)})")
    progress.empty()

    if not roic_map:
        st.warning("ROIC를 계산할 수 있는 종목이 없습니다.")
        return

    # ── 전체 종목 x 연도 ROIC 표 ─────────────────────────────
    st.subheader(f"연도별 ROIC 표 ({len(roic_map)}/{len(tickers)}개 종목 데이터 확보)")
    table = pd.DataFrame(roic_map).T
    # 회사마다 회계연도 마감월이 달라(9월/6월/12월 등) 같은 연도라도 컬럼(날짜)이 서로 다르다.
    # 연도로 묶어 집계하면 한 회사·한 연도에는 실제로 값이 하나뿐이므로 mean()이 그 값을 그대로 남긴다.
    table.columns = [c.year for c in table.columns]
    table = table.T.groupby(level=0).mean().T
    table = table.sort_index(axis=1)
    # 회사마다 최근 데이터가 있는 연도가 다를 수 있어(회계연도 마감월 차이), 마지막 컬럼이 아니라
    # 각 회사(행)별로 가장 최근에 값이 있는 연도를 찾아야 한다 — 행 방향으로 ffill 후 마지막 컬럼을 취하면 된다.
    table["최근 ROIC(%)"] = table.ffill(axis=1).iloc[:, -1]
    table = table.sort_values("최근 ROIC(%)", ascending=False)
    display_table = table.copy()
    display_table.index = [_label(t, wiki_names) for t in display_table.index]
    for col in display_table.columns:
        display_table[col] = display_table[col].map(lambda v: f"{v:.1f}" if pd.notna(v) else "-")
    st.dataframe(display_table, use_container_width=True)

    st.markdown("---")

    # ── 고ROIC 종목만 그래프 (임계치 사용자 조정 가능) ─────────
    st.subheader("🎯 고(高)ROIC 종목 추세")
    with st.expander("📖 이 그래프를 어떻게 해석하면 될까요?", expanded=False):
        st.markdown(
            f"- 아래 슬라이더로 고른 기준(%) **이상**인 종목만 골라 연도별 ROIC 변화를 선으로 그립니다. "
            f"워런 버핏이 언급해 유명해진 기준은 **{BUFFETT_ROIC_BENCHMARK:.0f}%**이지만, 이 기준을 그대로 "
            f"적용하면 대부분의 우량기업도 걸러질 만큼 엄격해서, 기본값은 조금 더 완만한 "
            f"**{DEFAULT_ROIC_THRESHOLD:.0f}%**로 잡아뒀습니다.\n"
            "- **선이 우상향**하면 그 회사가 갈수록 적은 자본으로 더 많은 이익을 내고 있다는 뜻 — "
            "사업 경쟁력(해자)이 강해지고 있다는 긍정적 신호로 흔히 해석됩니다.\n"
            "- **선이 우하향**하면 자본 대비 수익성이 나빠지고 있다는 뜻이며, 업황 둔화·경쟁 심화·"
            "대규모 투자(아직 이익으로 이어지지 않은 투하자본 증가) 등을 의심해볼 수 있습니다.\n"
            "- 한두 해 반짝 높은 것보다, **여러 해 연속으로 기준을 넘는 종목**이 버핏이 말한 "
            "'꾸준히 우수한 사업'에 더 가깝습니다 — 표에서 여러 연도 수치를 함께 확인하세요."
        )
    threshold = st.slider(
        "그래프에 표시할 최소 ROIC(%) 기준", min_value=5, max_value=50,
        value=int(DEFAULT_ROIC_THRESHOLD), step=5,
    )
    high_roic_tickers = table[table["최근 ROIC(%)"] >= threshold].index.tolist()
    st.caption(f"최근 ROIC {threshold}% 이상 종목: {len(high_roic_tickers)}개")
    if high_roic_tickers:
        high_roic_map = {t: roic_map[t] for t in high_roic_tickers}
        st.plotly_chart(
            line_chart(high_roic_map, {t: _label(t, wiki_names) for t in high_roic_tickers},
                       title="", height=460, dark=dark, markers=True),
            use_container_width=True,
        )
        st.caption("종목: " + ", ".join(_label(t, wiki_names) for t in high_roic_tickers))
    else:
        st.info(f"조회한 {len(roic_map)}개 종목 중 최근 ROIC {threshold}% 이상인 종목이 없습니다.")

    st.caption(
        "데이터 출처: yfinance (연간 재무제표). ROIC = EBIT × (1 − 유효세율) ÷ Invested Capital. "
        "본 분석은 투자 조언이 아니며 참고용입니다."
    )
