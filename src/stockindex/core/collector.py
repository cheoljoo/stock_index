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
