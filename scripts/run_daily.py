#!/usr/bin/env python3
"""Daily data collection, alert evaluation, and mail dispatch.

cron이 매일 04:00에 이 스크립트를 실행한다 (`crontab -l` 참고, README "자동 수집" 절 참조).
대시보드(app.py)는 이 스크립트가 저장한 결과만 읽으므로, **대시보드에 보이는 지표 값과
메일 알림 내용은 이 스크립트가 최근에 성공적으로 실행됐을 때만 최신이다.**

```mermaid
flowchart TD
    cron["cron 04:00"] --> main
    subgraph main["run_daily.py main()"]
        direction TB
        S1["1. collect_all() — 전 지표 수집 → Parquet/SQLite 저장"]
        S2["2. PortfolioProvider — 국민연금 자산배분 스냅샷 저장"]
        S3["3. run_alerts() — thresholds.yaml 평가, 신규 도달만 필터"]
        S4["4. send_alert() — 도달 항목 있으면 HTML 메일 발송"]
        S5["5. screen_kospi200() — 외국인·기관 동반매수/매도 연속일수 스캔 → 저장 + 다이제스트 메일"]
        S6["6. screen_ownership_kospi200() — 외국인 지분율 지속증가/일시급증 스캔 → 저장"]
        S1 --> S2 --> S3 --> S4 --> S5 --> S6
    end
    main --> Dash["대시보드(app.py)가 다음 조회 시 새 데이터 표시"]
    main --> Mail["수신자 메일함 (도달 시에만)"]
```
"""
from __future__ import annotations
import io
import sys
import time
import traceback
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parents[1] / ".env")

from datetime import date, datetime, timedelta
import argparse
from stockindex.config.loader import load_settings, load_thresholds
from stockindex.core.collector import collect_all
from stockindex.core.alerts import run_alerts
from stockindex.core.screener import screen_kospi200, screen_ownership_kospi200
from stockindex.notify.mailer import send_alert, send_flow_screen_digest
from stockindex.notify.report import send_report
from stockindex.providers import krx_openapi
from stockindex.providers.portfolio_provider import PortfolioProvider
from stockindex.storage import db as _db


class _Tee(io.TextIOBase):
    """출력을 원래 스트림(cron 의 collect.log)과 이번 실행 전용 로그 파일에 같이 쓴다."""
    def __init__(self, stream, copy):
        self.stream, self.copy = stream, copy

    def write(self, text):
        self.stream.write(text)
        self.copy.write(text)
        self.flush()
        return len(text)

    def flush(self):
        self.stream.flush()
        self.copy.flush()


def _last_run_log() -> str:
    """collect.log 에서 마지막 실행분만 잘라낸다 (--report-only 용)."""
    path = Path(__file__).parents[1] / "logs" / "collect.log"
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    i = text.rfind("=== run_daily ")
    return text[i:] if i >= 0 else text


def main():
    """일일 파이프라인 진입점: 수집 → 평가 → 스크리너 → 결과 메일.

    `--keys`로 특정 지표만 수집하거나(디버깅용), `--dry-run`으로 메일 발송만 건너뛸 수 있다.
    `--report-only`는 수집 없이 마지막 실행 결과로 보고 메일만 다시 보낸다.
    실행이 실패해도 보고 메일은 보낸다.
    """
    parser = argparse.ArgumentParser(description="Daily stock index collection & alerts")
    parser.add_argument("--keys", nargs="*", help="Specific indicator keys to collect (default: all)")
    parser.add_argument("--dry-run", action="store_true", help="Collect but skip sending email")
    parser.add_argument("--report-only", action="store_true", help="Send the report for the last run without collecting")
    args = parser.parse_args()

    if args.report_only:
        log_text = _last_run_log()
        ok = "=== Done ===" in log_text
        print(f"[report] {send_report(log_text, ok=ok, send=not args.dry_run)}")
        return

    run_dir = Path(__file__).parents[1] / "logs" / "runs"
    run_dir.mkdir(parents=True, exist_ok=True)
    for old in run_dir.glob("run_daily_*.log"):
        if datetime.fromtimestamp(old.stat().st_mtime) < datetime.now() - timedelta(days=30):
            old.unlink()
    log_path = run_dir / f"run_daily_{datetime.now():%Y%m%d_%H%M%S}.log"

    started, ok = time.time(), False
    original = sys.stdout, sys.stderr
    with log_path.open("w", encoding="utf-8") as log_file:
        sys.stdout, sys.stderr = _Tee(original[0], log_file), _Tee(original[1], log_file)
        try:
            _pipeline(args)
            ok = True
        except BaseException:
            log_file.write(traceback.format_exc())
            log_file.flush()
            raise
        finally:
            try:
                send_report(log_path.read_text(encoding="utf-8"), ok=ok,
                            elapsed=time.time() - started, send=not args.dry_run)
            except Exception as e:          # 보고 실패가 수집 결과에 영향을 주면 안 된다
                print(f"[report] ⚠️ 결과 메일 실패: {type(e).__name__}: {e}")
            finally:
                sys.stdout, sys.stderr = original


def _pipeline(args):
    settings = load_settings()
    db_path = settings.storage.db_path
    today = date.today()

    print(f"=== run_daily {today} ===")

    # 1. Collect
    series_map = collect_all(keys=args.keys)
    print(f"\n[done] Collected {len(series_map)} indicators")

    # 2. Portfolio snapshots
    prov = PortfolioProvider()
    hist = prov.get_allocation_history("nps")
    if hist:
        _db.init_db(db_path)
        _db.save_portfolio_snapshot(db_path, "nps", today, hist)
        print(f"[portfolio] saved {len(hist)} NPS rows")

    # 3. Alert evaluation
    recipients, thresholds_cfg = load_thresholds()
    suppress = settings.alert.suppress_duplicate_days
    triggered = run_alerts(series_map, recipients, thresholds_cfg, db_path, today, suppress)
    print(f"\n[alerts] {len(triggered)} threshold(s) triggered")
    for item in triggered:
        print(f"  {item['indicator']} [{item['level']}] = {item['value']:.4f}")

    # 4. Send mail
    if triggered and not args.dry_run:
        send_alert(triggered)
    elif triggered and args.dry_run:
        print("[dry-run] Skipping email send")

    # KRX Open API 일별 시세 캐시 채우기 (대시보드 첫 조회 대기 제거)
    if krx_openapi.available():
        n = krx_openapi.warm_cache()
        print(f"\n[krx-openapi] 시세 캐시 갱신: 새로 받은 거래일 {n}일")

    # 5. KOSPI200 investor flow screener (외국인·기관 동반매수/매도 연속일수)
    screener_cfg = settings.screener
    run = screen_kospi200(min_days=screener_cfg.min_days)
    _db.init_db(db_path)
    _db.save_screen_run(db_path, today, run.universe_size, run.is_full_kospi200)
    if run.aborted:
        print(f"\n[screener] ⚠️ KRX 조회 중단 — {run.aborted}")
    if not run.is_full_kospi200 and run.universe_size:
        print(f"\n[screener] ⚠️ KOSPI200 정식 API 조회 실패 — 대형주 근사 리스트({run.universe_size}종목)로 대체")
    if run.results:
        _db.save_investor_flow_screen(db_path, today, run.results)
        print(f"[screener] {len(run.results)}/{run.universe_size} stock(s) with >= {screener_cfg.min_days}d streak")
        if not args.dry_run:
            recipients, _ = load_thresholds()
            send_flow_screen_digest(
                run.results, screener_cfg.notify_min_days,
                recipients.get(screener_cfg.notify, []),
            )
    else:
        print("\n[screener] no results (KRX 로그인 미설정이거나 조건 충족 종목 없음)")

    # 6. KOSPI200 foreign ownership screener (지분율 지속증가/일시급증)
    own_run = screen_ownership_kospi200(
        lookback_days=screener_cfg.ownership_lookback_days,
        steady_min_change=screener_cfg.ownership_steady_min_change_pct,
        steady_min_up_ratio=screener_cfg.ownership_steady_min_up_ratio,
        spike_min_daily_change=screener_cfg.ownership_spike_min_daily_change_pct,
    )
    _db.save_ownership_screen_run(db_path, today, own_run.universe_size, own_run.is_full_kospi200)
    if own_run.aborted:
        print(f"\n[ownership] ⚠️ KRX 조회 중단 — {own_run.aborted}")
    if not own_run.is_full_kospi200 and own_run.universe_size:
        print(f"\n[ownership] ⚠️ KOSPI200 정식 API 조회 실패 — 대형주 근사 리스트({own_run.universe_size}종목)로 대체")
    if own_run.results:
        _db.save_ownership_screen(db_path, today, own_run.results)
        steady_n = sum(1 for r in own_run.results if r.is_steady_increase)
        spike_n = sum(1 for r in own_run.results if r.is_spike)
        print(f"[ownership] {len(own_run.results)}/{own_run.universe_size} stock(s) — 지속증가 {steady_n}, 급증 {spike_n}")
    else:
        print("\n[ownership] no results (KRX 로그인 미설정이거나 조건 충족 종목 없음)")

    print("\n=== Done ===")


if __name__ == "__main__":
    main()
