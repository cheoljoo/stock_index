"""매일 지표 데이터를 수집해 저장소(Parquet/SQLite)에 반영하는 오케스트레이션 계층.

```mermaid
flowchart LR
    A[registry.build_registry] -->|key -> config, provider| B(collect_all)
    B -->|provider.fetch symbol,start,end| C[각 Provider]
    C -->|pd.Series| B
    B -->|save_series| D[(Parquet: data/series/*.parquet)]
    B -->|upsert_indicator_meta| E[(SQLite: indicators 테이블)]
```
"""
from __future__ import annotations
from datetime import date, timedelta
import pandas as pd
from stockindex.config.loader import load_settings
from stockindex.storage import timeseries as ts
from stockindex.storage import db as _db
from .registry import build_registry


def collect_all(
    start: date | None = None,
    end: date | None = None,
    keys: list[str] | None = None,
) -> dict[str, pd.Series]:
    """활성화된(enabled) 지표를 모두(또는 `keys`로 지정한 것만) 수집해 저장한다.

    지표 하나가 실패해도 나머지 수집은 계속 진행된다(예외를 잡아 로그만 남김).

    Args:
        start: 조회 시작일. 생략 시 `settings.collect.lookback_days`만큼 과거로 계산.
        end: 조회 종료일. 생략 시 오늘.
        keys: 수집할 지표 key 목록. 생략 시 registry의 전체 지표.

    Returns:
        {지표key: 수집된 시계열(pd.Series)} — 수집에 성공한 지표만 포함.
    """
    settings = load_settings()
    db_path = settings.storage.db_path
    parquet_dir = settings.storage.parquet_dir
    lookback = settings.collect.lookback_days

    _db.init_db(db_path)
    registry = build_registry()

    if end is None:
        end = date.today()
    if start is None:
        start = end - timedelta(days=lookback)

    results: dict[str, pd.Series] = {}
    target_keys = keys or list(registry.keys())

    for key in target_keys:
        if key not in registry:
            print(f"[collector] '{key}' not in registry, skipping")
            continue
        cfg, provider = registry[key]
        print(f"[collector] fetching {key} ({cfg.symbol}) via {cfg.provider}...")
        try:
            series = provider.fetch(cfg.symbol, start, end)
            if not series.empty:
                ts.save_series(parquet_dir, key, series)
                _db.upsert_indicator_meta(
                    db_path, key,
                    display_name=cfg.display_name,
                    provider=cfg.provider,
                    symbol=cfg.symbol,
                    unit=cfg.unit,
                    category=cfg.category,
                    enabled=1,
                    last_fetched=str(end),
                )
                results[key] = series
                print(f"  -> {len(series)} rows, latest={series.iloc[-1]:.4f}")
            else:
                print(f"  -> empty (no data returned)")
        except Exception as e:
            print(f"  -> ERROR: {e}")
    return results


def load_all_series(
    keys: list[str] | None = None,
    start: date | None = None,
    end: date | None = None,
) -> dict[str, pd.Series]:
    """저장소(Parquet)에서 이미 수집된 시계열을 읽기만 한다 (네트워크 호출 없음).

    대시보드가 화면을 그릴 때 사용하는 함수 — 데이터 수집(`collect_all`)과
    분리되어 있어 대시보드는 항상 마지막 cron 수집 결과를 읽는다.

    Args:
        keys: 조회할 지표 key 목록. 생략 시 저장된 전체 지표.
        start, end: 기간 필터.

    Returns:
        {지표key: 시계열} — 데이터가 있는 지표만 포함.
    """
    settings = load_settings()
    parquet_dir = settings.storage.parquet_dir
    available = ts.list_available(parquet_dir)
    target = keys or available
    result = {}
    for key in target:
        s = ts.load_series(parquet_dir, key, start=start, end=end)
        if not s.empty:
            result[key] = s
    return result
