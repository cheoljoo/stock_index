.PHONY: help install install-dev venv env collect collect-dry dashboard stop test lint clean

PYTHON     := .venv/bin/python
UV         := uv
VENV       := .venv
SRC        := src/stockindex/dashboard/app.py
COLLECT    := scripts/run_daily.py
HOST       := 0.0.0.0
PORT       := 8501
PID_FILE   := .streamlit.pid

help:
	@echo "Usage: make <target>"
	@echo ""
	@echo "  install       가상환경 생성 + 패키지 설치 (런타임)"
	@echo "  install-dev   가상환경 생성 + 패키지 설치 (dev 포함)"
	@echo "  env           .env.example → .env 복사 (최초 1회)"
	@echo "  collect       전체 지표 데이터 수집"
	@echo "  collect-dry   수집 테스트 (메일 미발송)"
	@echo "  dashboard     Streamlit 대시보드 시작 (http://$(HOST):$(PORT))"
	@echo "  stop          실행 중인 대시보드 종료"
	@echo "  test          pytest 실행"
	@echo "  lint          ruff 코드 검사 (설치된 경우)"
	@echo "  clean         캐시·빌드 산출물 삭제"
	@echo ""
	@echo "  nginx-install nginx 리버스 프록시 설정 (최초 1회, sudo 필요)"
	@echo "  nginx-reload  nginx 설정 반영 (sudo 필요)"
	@echo "  nginx-status  nginx 상태 확인"
	@echo ""
	@echo "  service-install  systemd 서비스 등록·자동시작 (최초 1회, sudo 필요)"
	@echo "  service-start    서비스 시작"
	@echo "  service-stop     서비스 중지"
	@echo "  service-restart  서비스 재시작"
	@echo "  service-status   서비스 상태 확인"
	@echo "  service-log      최근 로그 50줄 출력"

# ── 환경 구성 ──────────────────────────────────────────────

venv:
	$(UV) venv $(VENV)

install: venv
	$(UV) pip install -e "." --python $(VENV)/bin/python

install-dev: venv
	$(UV) pip install -e ".[dev]" --python $(VENV)/bin/python

env:
	@if [ -f .env ]; then \
		echo ".env 파일이 이미 존재합니다. 덮어쓰지 않습니다."; \
	else \
		cp .env.example .env; \
		echo ".env 파일을 생성했습니다. API 키를 채워주세요."; \
	fi

# ── 데이터 수집 ────────────────────────────────────────────

collect:
	$(PYTHON) $(COLLECT)

collect-dry:
	$(PYTHON) $(COLLECT) --dry-run

# ── 대시보드 ───────────────────────────────────────────────

dashboard:
	@echo "대시보드 시작 (포그라운드): http://psncs.iptime.org/stock_index/"
	$(VENV)/bin/streamlit run $(SRC) \
		--server.address $(HOST) \
		--server.port $(PORT) \
		--server.headless true \
		--server.baseUrlPath /stock_index \
		--browser.gatherUsageStats false

# ── systemd 서비스 관리 (자동 시작, 재부팅 후에도 유지) ──────────
service-install:
	sudo cp stockindex.service /etc/systemd/system/stockindex.service
	sudo systemctl daemon-reload
	sudo systemctl enable stockindex
	sudo systemctl start stockindex
	@echo "서비스 등록 완료 → http://psncs.iptime.org/stock_index/"

service-start:
	sudo systemctl start stockindex

service-stop:
	sudo systemctl stop stockindex

service-restart:
	sudo systemctl restart stockindex

service-status:
	sudo systemctl status stockindex --no-pager

service-log:
	@tail -50 logs/dashboard.log

stop: service-stop

# ── nginx 리버스 프록시 ────────────────────────────────────

nginx-install:
	@echo "/etc/nginx/conf.d/candle.conf 에 stock_index location 블록을 추가합니다..."
	sudo $(PYTHON) scripts/patch_nginx.py
	sudo nginx -t && sudo systemctl reload nginx
	@echo "nginx 설정 완료 → http://psncs.iptime.org/stock_index/"

nginx-reload:
	sudo nginx -t && sudo systemctl reload nginx

nginx-status:
	sudo systemctl status nginx --no-pager

# ── 테스트 & 린트 ──────────────────────────────────────────

test:
	$(VENV)/bin/pytest tests/ -v

lint:
	@$(VENV)/bin/ruff check src/ || echo "ruff가 설치되지 않았습니다: uv pip install ruff"

# ── 정리 ──────────────────────────────────────────────────

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null; true
	find . -type d -name "*.egg-info"  -exec rm -rf {} + 2>/dev/null; true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null; true
	rm -f $(PID_FILE)
