# 📊 Stock Index Dashboard

주식 투자에 필요한 다양한 지표를 매일 자동 수집하고, 수치와 그래프로 보여주는 오픈소스 대시보드.

## 기능

- **Config 기반 지표 관리**: `config/indicators.yaml`에서 지표 이름 + on/off + provider 설정
- **임의 묶음 구성**: `config/groups.yaml`에서 지표 묶음을 자유롭게 정의 (개수 제한 없음)
- **추세 자동 분류**: 상향 / 하향 / 울퉁불퉁 / 일정 — 같은 방향 지표끼리 모아 비교
- **단계별 임계치 알림**: `config/thresholds.yaml`에서 단계별 조건 설정, 도달 시 HTML 메일 발송
- **대시보드**: Streamlit + Plotly 인터랙티브 차트
- **국부펀드 포트폴리오**: 국민연금 자산배분 변화 추이 (표 + 스택 차트)
- **데드캣 바운스 분석**: 공매도·거래량·투자자별(외국인/기관/개인) 수급 + 글로벌 동조화 기준으로
  일시적 기술적 반등(데드캣 바운스)인지 진짜 추세 전환인지 판별하고, 어제 종가 기준 결론과 근거를 표시

## 기본 지표

| 구분 | 지표 |
|---|---|
| 주가지수 | KOSPI200, KOSDAQ150, S&P500, NASDAQ100, CSI300, EuroStoxx50, Nikkei225 |
| ETF | 반도체 SOXX, SMH |
| 암호화폐 | 비트코인, 이더리움 |
| 원자재 | 금, 원유(WTI) |
| 변동성 | VIX |
| 환율 | USD/KRW, USD/JPY, USD/CNY, EUR/USD |
| 금리 | 미국 기준금리·2년·10년, 일본·유럽 10년, 한국 기준금리 |
| 거시지표 | 미국 CPI·실업률·GDP·M2·가계부채 |
| 국부펀드 | 국민연금 포트폴리오 |

## 빠른 시작 (Makefile)

```bash
make install          # 가상환경 생성 + 패키지 설치
make env              # .env 파일 생성 (API 키 입력 필요)
make nginx-install    # nginx 리버스 프록시 등록 (최초 1회, sudo 필요)
make service-install  # systemd 서비스 등록·자동시작 (최초 1회, sudo 필요)
make collect          # 데이터 수집
```

전체 타겟 목록은 `make help`로 확인할 수 있습니다.

---

## 설치 (수동)

```bash
git clone https://github.com/your-id/stock-index.git
cd stock-index
uv venv .venv && source .venv/bin/activate
uv pip install -e ".[dev]"
cp .env.example .env   # API 키 설정
```

## API 키 설정

| 서비스 | 용도 | 발급처 |
|---|---|---|
| FRED | 미국 금리·거시지표 | https://fred.stlouisfed.org/docs/api/api_key.html |
| 한국은행 ECOS | 한국 금리·거시지표 | https://ecos.bok.or.kr/api/ |
| SMTP | 임계치 알림 메일 | Gmail 앱 비밀번호 등 |
| CoinGecko | 코인 가격 | 무료 (키 없음, 365일 이내 데이터) |
| yfinance | 주가·ETF·환율·원자재 | 무료 (키 없음) |
| KRX (data.krx.co.kr) | 공매도·투자자별 수급 (데드캣 바운스 분석) | 무료 회원가입 필요 (`KRX_ID`, `KRX_PW`). 미설정 시 주가·거래량 분석만 제공 |

## 사용법

### Makefile 타겟 전체 목록

| 타겟 | 설명 |
|---|---|
| `make install` | 가상환경 생성 + 런타임 패키지 설치 |
| `make install-dev` | 가상환경 생성 + dev(pytest 등) 포함 설치 |
| `make env` | `.env.example` → `.env` 복사 (이미 있으면 건너뜀) |
| `make collect` | 전체 지표 데이터 수집 |
| `make collect-dry` | 수집 테스트 (메일 미발송) |
| `make dashboard` | 대시보드 포그라운드 실행 (Ctrl+C로 종료) |
| `make stop` | 서비스 중지 |
| `make test` | pytest 실행 |
| `make lint` | ruff 코드 검사 |
| `make clean` | 캐시·빌드 산출물 삭제 |
| `make nginx-install` | nginx 리버스 프록시 등록 (최초 1회, sudo 필요) |
| `make nginx-reload` | nginx 설정 반영 (sudo 필요) |
| `make nginx-status` | nginx 상태 확인 |
| `make service-install` | systemd 서비스 등록·자동시작 (최초 1회, sudo 필요) |
| `make service-start` | 서비스 시작 |
| `make service-stop` | 서비스 중지 |
| `make service-restart` | 서비스 재시작 |
| `make service-status` | 서비스 상태 확인 |
| `make service-log` | 최근 로그 50줄 출력 |

### 데이터 수집
```bash
# Makefile 사용
make collect
make collect-dry   # 메일 미발송 테스트

# 직접 실행
python scripts/run_daily.py
python scripts/run_daily.py --keys sp500 vix gold bitcoin
python scripts/run_daily.py --dry-run
```

### 대시보드 실행

대시보드는 **systemd 서비스**로 관리합니다. 서버 재부팅 시 자동 시작되고, 비정상 종료 시 자동 재시작됩니다.

```bash
# 최초 1회 서비스 등록 (sudo 필요)
make service-install

# 이후 관리
make service-status   # 상태 확인
make service-restart  # 재시작
make service-log      # 로그 확인
make service-stop     # 중지
```

개발 중 포그라운드 실행이 필요한 경우:
```bash
make dashboard   # Ctrl+C로 종료
```

### 웹 접속

| 접속 경로 | URL |
|---|---|
| 외부 (인터넷, 홈페이지) | http://psncs.iptime.org/ |
| 외부 (인터넷, 대시보드) | http://psncs.iptime.org/stock_index/ |
| 로컬 | http://localhost:8501/stock_index |

외부 접속은 **nginx 리버스 프록시** (포트 80 `/stock_index/` → 8501) 를 통해 동작합니다.  
기존 서비스(`/`, `/stock_candle/`, `/infinite_buying/`, `/news/` 등)는 그대로 유지됩니다.  
포트 8501을 공유기에서 별도 포워딩할 필요 없습니다.

#### nginx 리버스 프록시 최초 설정 (1회)

기존 `/etc/nginx/conf.d/candle.conf` 에 `/stock_index` location 블록을 자동으로 추가합니다.

```bash
make nginx-install   # sudo 비밀번호 필요
```

설정 참고 파일: `nginx/stockindex.conf`  
패치 스크립트: `scripts/patch_nginx.py` (이미 추가된 경우 건너뜀)

#### systemd 서비스 파일

서비스 정의: `stockindex.service`  
로그 위치: `logs/dashboard.log`

서비스는 부팅 시 자동 시작(`WantedBy=multi-user.target`)되며,  
프로세스 종료 시 5초 후 자동 재시작(`Restart=always`)됩니다.

### 자동 수집 (cron)

매일 오전 4시에 전체 지표를 자동 수집합니다. 이미 등록되어 있습니다.

```
0 4 * * * /home/cheoljoo/code/stock_index/.venv/bin/python scripts/run_daily.py >> /home/cheoljoo/code/stock_index/logs/collect.log 2>&1
```

로그 확인:
```bash
tail -f logs/collect.log
```

수동으로 등록하거나 수정하려면:
```bash
crontab -e
```

### 테스트
```bash
make test
# 또는
pytest tests/ -v
```

## 지표 추가 방법

`config/indicators.yaml`에 블록만 추가하면 코드 수정 없이 동작합니다:

```yaml
indicators:
  my_new_indicator:
    enabled: true
    display_name: "새 지표"
    provider: yfinance      # yfinance | fred | coingecko | ecos | portfolio
    symbol: "AAPL"
    unit: "USD"
    category: equity
    trend_window: 20
```

## 새 데이터 소스 추가 방법

```python
# src/stockindex/providers/my_provider.py
from stockindex.providers.base import Provider

class MyProvider(Provider):
    name = "my_source"  # 이름만 정하면 자동 등록

    def fetch(self, symbol, start, end):
        # ... 데이터 가져오는 로직 ...
        return pd.Series(...)
```

그런 다음 `src/stockindex/providers/__init__.py`에 import 추가, config에서 `provider: my_source` 사용.

## 데이터 소스 및 라이선스

| 소스 | 용도 | 라이선스/약관 |
|---|---|---|
| [yfinance](https://github.com/ranaroussi/yfinance) | 주가·ETF·환율·원자재 | Apache 2.0 (Yahoo Finance 약관 준수 필요) |
| [FRED (Federal Reserve)](https://fred.stlouisfed.org) | 미국 금리·거시지표 | Public domain, FRED ToS 준수 |
| [한국은행 ECOS](https://ecos.bok.or.kr/api/) | 한국 금리·거시지표 | 공공데이터 이용허락 |
| [CoinGecko](https://www.coingecko.com/en/api) | 코인 가격 | CoinGecko ToS 준수 |
| [국민연금 공시](https://fund.nps.or.kr) | 포트폴리오 | 공개 공시 데이터 |
| [KRX 정보데이터시스템](https://data.krx.co.kr) ([pykrx](https://github.com/sharebook-kr/pykrx)) | 공매도·투자자별 수급 (데드캣 바운스 분석) | KRX 이용약관 준수, 무료 회원 로그인 필요 |

> **면책조항**: 본 프로젝트는 투자 조언을 제공하지 않습니다. 데이터 정확성을 보장하지 않으며, 투자 결정에 대한 책임은 사용자에게 있습니다.

## 라이선스

MIT License — 자유롭게 사용, 수정, 배포 가능합니다.
