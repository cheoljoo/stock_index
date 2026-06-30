from __future__ import annotations
from datetime import date
import pandas as pd
from stockindex.config.schema import ThresholdLevel
from stockindex.storage import db as _db


def evaluate_threshold(series: pd.Series, level: ThresholdLevel) -> bool:
    if series.empty:
        return False
    cond = level.condition
    latest = float(series.iloc[-1])
    op = cond.op
    if op == ">=":
        return latest >= cond.value
    if op == "<=":
        return latest <= cond.value
    if op == "pct_change":
        window = cond.window
        if len(series) < window + 1:
            return False
        prev = float(series.iloc[-(window + 1)])
        if prev == 0:
            return False
        pct = (latest - prev) / abs(prev) * 100
        return pct >= cond.value if cond.value > 0 else pct <= cond.value
    if op == "cross":
        # cross: latest crosses above moving average of window days
        if len(series) < cond.window:
            return False
        ma = series.iloc[-cond.window:].mean()
        prev = float(series.iloc[-2]) if len(series) >= 2 else latest
        return prev < ma <= latest
    return False


def run_alerts(
    series_map: dict[str, pd.Series],
    recipients: dict[str, list[str]],
    thresholds: dict[str, list[ThresholdLevel]],
    db_path: str,
    today: date,
    suppress_days: int = 1,
) -> list[dict]:
    """Evaluate all thresholds and return triggered alerts (not yet suppressed)."""
    triggered = []
    for indicator, levels in thresholds.items():
        series = series_map.get(indicator)
        if series is None or series.empty:
            continue
        latest_val = float(series.iloc[-1])
        for level in levels:
            if not evaluate_threshold(series, level):
                continue
            inserted = _db.record_alert(db_path, indicator, level.level, today, latest_val)
            if not inserted:
                continue  # suppressed duplicate
            notify_emails: list[str] = []
            for key in level.notify_keys():
                notify_emails.extend(recipients.get(key, []))
            triggered.append({
                "indicator": indicator,
                "level": level.level,
                "value": latest_val,
                "recipients": list(set(notify_emails)),
            })
    return triggered
