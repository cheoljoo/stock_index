"""`config/thresholds.yaml`에 정의된 단계별 임계치를 평가하고, 도달한 항목을 리턴하는 엔진.

```mermaid
flowchart TD
    A["thresholds.yaml (지표별 level 목록)"] --> B(run_alerts)
    C["series_map (collect_all 결과)"] --> B
    B -->|evaluate_threshold: >=, <=, pct_change, cross| D{도달?}
    D -->|No| B
    D -->|Yes| E["db.record_alert (중복 발송 방지)"]
    E -->|신규| F["triggered 목록에 추가 (지표, level, 값, 수신자)"]
    E -->|중복(이미 발송됨)| B
    F --> G["notify.mailer.send_alert (run_daily.py에서 호출)"]
```
"""
from __future__ import annotations
from datetime import date
import pandas as pd
from stockindex.config.schema import ThresholdLevel
from stockindex.storage import db as _db


def evaluate_threshold(series: pd.Series, level: ThresholdLevel) -> bool:
    """시계열의 최신값이 하나의 임계 조건(level.condition)을 충족하는지 평가한다.

    지원하는 연산자:
        - `>=`, `<=`: 최신값과 절대 기준값 비교
        - `pct_change`: `window`일 전 대비 등락률(%)이 기준값 이상(양수) 또는 이하(음수)
        - `cross`: 최신값이 `window`일 이동평균을 아래→위로 돌파했는지

    Args:
        series: 평가할 시계열 (최신값이 마지막 원소).
        level: 조건(`level.condition`)을 담은 임계치 정의.

    Returns:
        조건 충족 여부.
    """
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
