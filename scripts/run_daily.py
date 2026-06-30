#!/usr/bin/env python3
"""Daily data collection, alert evaluation, and mail dispatch."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from datetime import date
import argparse
from stockindex.config.loader import load_settings, load_thresholds
from stockindex.core.collector import collect_all
from stockindex.core.alerts import run_alerts
from stockindex.notify.mailer import send_alert
from stockindex.providers.portfolio_provider import PortfolioProvider
from stockindex.storage import db as _db


def main():
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
