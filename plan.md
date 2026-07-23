# 주식 지표 수집 & 대시보드 시스템 구현 계획

## Context (왜 만드는가)

주식 투자에 필요한 다양한 지표(국내외 지수, ETF, 코인, 원자재, 금리, 환율, 거시지표,
국부펀드 포트폴리오 등)를 **매일 자동 수집**하고, **수치 + 그래프**로 보여주는 오픈소스 대시보드.
핵심 요구사항은 **확장성**: 지표를 계속 추가/on-off 하고, 묶음(group)을 자유롭게 구성하며,
같은 추세끼리 묶어 보고, 단계별 임계치에 도달하면 메일로 알림을 보낸다.

**확정된 스택**: Python + Streamlit + Plotly / 데이터는 무료 소스 우선(yfinance·FRED·ECOS·CoinGecko)
/ 매일 cron 실행 / SQLite(메타·설정·알림이력) + Parquet(시계열).

설계의 중심은 **config(YAML) 기반 + provider 플러그인 패턴**으로, 코드 수정 없이
지표를 추가/제어할 수 있게 만드는 것이다.

---

## 1. 디렉토리 구조

```
stock_index/
├── README.md                  # 오픈소스 소개, 데이터 출처/라이선스/링크
├── pyproject.toml             # 의존성 (uv/pip), 패키지 메타
├── config/
│   ├── indicators.yaml        # 지표 정의 (on/off, provider, symbol, group, trend옵션)
│   ├── groups.yaml            # 사용자 정의 묶음 (임의 개수)
│   ├── thresholds.yaml        # 단계별 임계치 + 알림 대상
│   └── settings.yaml          # SMTP, 사이트 URL, 스케줄, 저장경로 등
├── src/stockindex/
│   ├── config/                # 설정 로딩·검증 (pydantic 스키마)
│   │   ├── schema.py
│   │   └── loader.py
│   ├── providers/             # 데이터 소스 플러그인 (확장 지점)
│   │   ├── base.py            # Provider 추상클래스 + 레지스트리
│   │   ├── yfinance_provider.py
│   │   ├── fred_provider.py
│   │   ├── ecos_provider.py        # 한국은행
│   │   ├── coingecko_provider.py
│   │   └── portfolio_provider.py   # 국부펀드 포트폴리오(공시)
│   ├── storage/               # SQLite + Parquet 추상화
│   │   ├── timeseries.py      # Parquet read/write
│   │   └── db.py              # SQLite (메타, 알림이력, 포트폴리오 스냅샷)
│   ├── core/
│   │   ├── registry.py        # indicator registry (config → provider 연결)
│   │   ├── collector.py       # 매일 수집 오케스트레이션
│   │   ├── trend.py           # 추세 분류 (상향/하향/울퉁불퉁/일정)
│   │   └── alerts.py          # 임계치 평가 엔진
│   ├── notify/
│   │   ├── mailer.py          # smtplib 발송
│   │   └── templates/alert.html.j2   # Jinja2 HTML 메일
│   └── dashboard/
│       ├── app.py             # Streamlit 진입점
│       └── components/        # 차트·그룹뷰·포트폴리오뷰
├── scripts/
│   └── run_daily.py           # cron이 호출하는 진입점 (수집→평가→알림)
└── tests/
```

---

## 2. Config 설계 (확장성의 핵심)

### 2-1. `indicators.yaml` — 지표 정의 + on/off
각 지표는 **이름(key) + provider + symbol + 메타**로 선언. on/off는 `enabled` 플래그.

```yaml
indicators:
  kospi200:
    enabled: true
    display_name: "KOSPI 200"
    provider: yfinance
    symbol: "^KS200"
    unit: "pt"
    category: equity_index
    trend_window: 20        # 추세 판단 기간(일)
  sp500:
    enabled: true
    display_name: "S&P 500"
    provider: yfinance
    symbol: "^GSPC"
    category: equity_index
  us_10y_rate:
    enabled: true
    display_name: "미국 10년 금리"
    provider: fred
    symbol: "DGS10"
    category: rate
  bitcoin:
    enabled: true
    provider: coingecko
    symbol: "bitcoin"
    category: crypto
  # ...신규 지표는 이 블록만 추가하면 됨 (코드 수정 불필요)
```

### 2-2. `groups.yaml` — 임의 개수의 묶음
사용자가 자유롭게 묶음을 정의(개수 제한 없음). 한 지표가 여러 묶음에 속해도 됨.

```yaml
groups:
  korea_market:
    display_name: "한국 시장"
    members: [kospi200, kosdaq100, usdkrw, kr_base_rate]
  global_equity:
    display_name: "글로벌 주가지수"
    members: [sp500, nasdaq100, csi300, euro_stoxx]
  safe_haven:
    display_name: "안전자산"
    members: [gold, us_10y_rate, vix]
  # ...묶음 무제한 추가 가능
```

### 2-3. `thresholds.yaml` — 단계별 임계치 + 알림 대상
지표별로 **단계(level)** 를 배열로 구성. 각 단계마다 조건/방향/메일 수신자 지정.

```yaml
recipients:
  default: ["a@x.com", "b@x.com"]
  risk_team: ["risk@x.com"]

thresholds:
  vix:
    - level: "주의"
      condition: { op: ">=", value: 20 }
      notify: default
    - level: "경고"
      condition: { op: ">=", value: 30 }
      notify: [default, risk_team]
    - level: "위험"
      condition: { op: ">=", value: 40 }
      notify: risk_team
  usdkrw:
    - level: "급등"
      condition: { op: "pct_change", value: 2.0, window: 1 }   # 1일 +2%
      notify: default
```
지원 op: `>=`, `<=`, `pct_change`(기간내 변화율), `cross`(이동평균 돌파) 등 → `alerts.py`에서 확장 가능.

### 2-4. `settings.yaml`
```yaml
site_url: "https://my-stock-dashboard.example.com"
storage: { db_path: "data/meta.db", parquet_dir: "data/series" }
smtp: { host: "...", port: 587, user: "...", password_env: "SMTP_PASSWORD", from: "..." }
schedule: { run_time: "18:00", tz: "Asia/Seoul" }
```
(비밀번호는 `password_env`로 환경변수 참조 → 오픈소스에 비밀 노출 방지)

---

## 3. Provider 플러그인 패턴 (데이터 소스 확장 지점)

`providers/base.py`:
```python
class Provider(ABC):
    name: str
    @abstractmethod
    def fetch(self, symbol: str, start: date, end: date) -> pd.Series: ...

PROVIDERS: dict[str, Provider] = {}     # 레지스트리
def register(p): PROVIDERS[p.name] = p
```
- 신규 소스 추가 = `Provider` 서브클래스 1개 작성 + `register()` → config에서 `provider: <name>`으로 참조.
- 초기 구현: **yfinance**(주가/ETF/환율/원자재/VIX), **FRED**(금리·미국 거시), **ECOS**(한국 금리·가계·기업 지표), **CoinGecko**(코인), **portfolio**(국부펀드 공시).
- `registry.py`가 config의 enabled 지표를 읽어 provider별로 묶어 일괄 호출(레이트리밋·재시도 처리).

---

## 4. 기본 지표 세트 (전부 config에 포함)

| category | 지표 | provider |
|---|---|---|
| equity_index | KOSPI200, KOSDAQ150*, S&P500, NASDAQ100, CSI300, EuroStoxx50 | yfinance |
| etf | 반도체 ETF(SOXX/SMH, KODEX반도체) | yfinance |
| crypto | 비트코인, 이더리움 | coingecko |
| commodity | 금(GC=F), 원유(CL=F) | yfinance |
| volatility | VIX | yfinance |
| rate | 한/미/일/유럽 기준금리·국채금리 | fred + ecos |
| fx | USD/KRW, USD/JPY, USD/CNY, EUR/USD | yfinance |
| macro | 미국·한국 가계/기업/국가 거시지표(부채·CPI·고용 등) | fred + ecos |
| fund | 국부펀드(국민연금 등) 포트폴리오 | portfolio |

\* 요청의 "KOSDAQ100"은 실제 지수명(KOSDAQ150)으로 매핑하되 config에서 조정 가능.
모든 항목은 config 한 줄로 on/off·추가.

---

## 5. 추세 분류 & 같은 방향끼리 묶어 보기

`core/trend.py` — 지정 기간(`trend_window`)의 시계열로 4개 추세 분류:
- **상향(up)**: 선형회귀 기울기 > +임계, R² 높음
- **하향(down)**: 기울기 < -임계
- **일정(flat)**: |기울기| 작고 변동성 낮음
- **울퉁불퉁(volatile)**: 변동성/방향전환 높고 R² 낮음

대시보드에서 on된 지표를 **추세 버킷별 4개 섹션**으로 자동 그룹핑해 같은 방향 그래프를 한곳에 모아 표시.
정규화(첫날=100 또는 z-score) 후 한 차트에 오버레이 → 스케일 다른 지표도 방향 비교 가능.

---

## 6. 임계치 평가 & 메일 알림

- `core/alerts.py`: 매일 수집 직후 `thresholds.yaml` 평가 → 도달한 (지표, level) 목록 생성.
- 중복 발송 방지: SQLite `alert_history`에 (indicator, level, date) 기록, 동일 단계 재발송 억제(설정 가능).
- `notify/mailer.py` + `alert.html.j2`: 도달 항목을 **HTML 표(수치·단계·변화율)** + **대시보드 링크(`site_url`)** 포함해 발송. 수신자는 threshold의 `notify` → recipients 매핑.

---

## 7. 국부펀드 포트폴리오 변화

- `portfolio_provider.py`: 공개 공시(예: 국민연금 운용현황) 파싱 → 보유종목·비중 스냅샷.
- SQLite `portfolio_snapshots`에 일/분기 단위 저장.
- 대시보드 전용 뷰: 비중 변화(증감 표), 시계열 스택 차트(수치 + 그래프) 표시.
- 공시 주기가 길므로 수집 주기는 지표와 분리(설정 가능).

---

## 8. 대시보드 (Streamlit)

- `dashboard/app.py`: 사이드바에서 group 선택/지표 토글, 본문에 차트.
- 뷰: ① 묶음별 뷰(groups.yaml) ② 추세 버킷 뷰(상향/하향/울퉁불퉁/일정) ③ 포트폴리오 뷰 ④ 알림 현황.
- Plotly 인터랙티브 차트(줌·툴팁), 최신 수치 카드(metric) + 전일대비.
- 데이터는 storage에서 읽기만 → 대시보드는 수집과 분리(매일 cron이 갱신).

---

## 9. 스케줄링 & 실행

- `scripts/run_daily.py`: 수집 → Parquet/SQLite 저장 → 추세 계산 → 임계치 평가 → 메일.
- cron 예: `0 18 * * 1-5 cd /path && uv run python scripts/run_daily.py`.
- README에 cron 등록법 + (선택) GitHub Actions 워크플로 예시 제공.

---

## 10. 오픈소스 메타

- `README.md`: 프로젝트 소개, 스크린샷, **데이터 출처별 링크/라이선스 고지**
  (yfinance/Yahoo, FRED, 한국은행 ECOS, CoinGecko — 각 이용약관·attribution),
  설치/설정/실행법, 지표·provider 추가 가이드(확장 방법).
- MIT 라이선스(권장), `.env.example`, CONTRIBUTING 간단 안내.
- 면책조항: 투자 조언 아님(데이터 정보 제공 목적).

### 참고 데이터 소스 링크
- yfinance: https://github.com/ranaroussi/yfinance (Yahoo Finance 비공식)
- FRED (미국 연준 경제데이터): https://fred.stlouisfed.org / API https://fred.stlouisfed.org/docs/api/fred/
- 한국은행 ECOS Open API: https://ecos.bok.or.kr/api/
- CoinGecko API: https://www.coingecko.com/en/api
- 국민연금 운용현황(공시): https://fund.nps.or.kr
- Streamlit: https://streamlit.io / Plotly: https://plotly.com/python/

---

## 11. 구현 단계 (점진적)

1. **스캐폴딩**: 디렉토리, pyproject, config 스키마(pydantic), loader.
2. **Storage**: Parquet/SQLite 래퍼.
3. **Provider 1종(yfinance) + registry + collector** → 소수 지표로 end-to-end 동작.
4. **나머지 provider**(FRED, ECOS, CoinGecko) + 기본 지표 세트 전체 config.
5. **trend 분류 + 대시보드**(묶음뷰·추세뷰).
6. **임계치 엔진 + 메일(HTML)**.
7. **포트폴리오 provider + 뷰**.
8. **cron/스케줄 + README/오픈소스 메타 + 테스트**.

---

## 12. 검증 방법

- **단위**: provider mock으로 fetch→저장, trend 분류(상승/하강/평탄/변동 합성 시계열로 분기 확인),
  alerts 평가(임계 경계값), mailer 템플릿 렌더(SMTP는 mock).
- **통합**: `run_daily.py`를 소수 지표로 실제 실행 → Parquet/SQLite에 행 생성 확인.
- **대시보드**: `streamlit run src/stockindex/dashboard/app.py` 로 띄워 묶음/추세/포트폴리오 뷰 렌더 확인.
- **메일**: MailHog 또는 로컬 SMTP 디버그 서버로 HTML·링크 포함 발송 확인.
- **config 확장 테스트**: indicators.yaml에 새 지표 한 줄 추가 → 코드 변경 없이 수집·표시되는지 확인.

---

## 13. 구현 이후 추가된 기능 (Addendum)

원래 계획(위 1~12절)은 초기 스캐폴딩 시점의 설계이며, 이후 실제 사용 중 다음 기능이 추가로
구현되었다 (최신 상세는 README.md, 각 모듈 docstring 참고):

- **`core/deadcat.py` + `dashboard/components/deadcat_view.py`**: 데드캣 바운스 분석.
  공매도·거래량·투자자수급·글로벌동조화 4개 신호로 반등의 진위 판별.
- **`core/uptrend.py` + `dashboard/components/uptrend_view.py`**: 상승 추세 전환 분석.
  이동평균 크로스·RSI·MACD·가격패턴·박스권·거래량·수급 7개 신호를 **상승/하락 대칭**으로 판별해
  5단계(strong_uptrend/building/neutral/weakening/strong_downtrend)로 결론.
- **`providers/krx_provider.py`**: 위 두 분석 전용 — pykrx로 시세/공매도/투자자수급을 실시간 조회.
  `check_krx_login()`으로 KRX_ID/KRX_PW 오인증을 화면에 직접 노출(콘솔 로그에만 의존하지 않음).
  이 provider는 `core/registry.py`의 일반 지표 파이프라인과는 별도 경로로, **매일 cron 수집 대상이
  아니며** 대시보드가 페이지를 그릴 때마다 그때그때 조회한다.
- 대시보드 사이드바 메뉴가 "📊 주식 지표"/"🐈‍⬛ 데드캣 바운스 분석"/"📈 상승 추세 전환 분석" 3개
  독립 페이지로 분리됨 (원래는 하나의 "뷰 선택" 라디오에 데드캣이 섞여 있었음).
- 두 분석 페이지 모두 선택 가능한 전체 종목(`deadcat_view.PRESET_TICKERS`)을 일괄 계산하는
  요약표를 페이지 하단에 제공.
