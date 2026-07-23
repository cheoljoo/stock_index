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
        S1 --> S2 --> S3 --> S4
    end
    main --> Dash["대시보드(app.py)가 다음 조회 시 새 데이터 표시"]
    main --> Mail["수신자 메일함 (도달 시에만)"]
```
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parents[1] / ".env")

from datetime import date
import argparse
from stockindex.config.loader import load_settings, load_thresholds
from stockindex.core.collector import collect_all
from stockindex.core.alerts import run_alerts
from stockindex.notify.mailer import send_alert
from stockindex.providers.portfolio_provider import PortfolioProvider
from stockindex.storage import db as _db


def main():
    """일일 파이프라인 진입점: 수집 → 포트폴리오 스냅샷 → 임계치 평가 → 메일 발송.

    `--keys`로 특정 지표만 수집하거나(디버깅용), `--dry-run`으로 메일 발송만 건너뛸 수 있다.
    """
    parser = argparse.ArgumentParser(description="Daily stock index collection & alerts")
    parser.add_argument("--keys", nargs="*", help="Specific indicator keys to collect (default: all)")
    parser.add_argument("--dry-run", action="store_true", help="Collect but skip sending email")
    args = parser.parse_args()

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

    print("\n=== Done ===")


if __name__ == "__main__":
    main()
