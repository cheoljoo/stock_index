from __future__ import annotations
from pathlib import Path
from datetime import date
import pandas as pd


def _path(parquet_dir: str | Path, key: str) -> Path:
    return Path(parquet_dir) / f"{key}.parquet"


def save_series(parquet_dir: str | Path, key: str, series: pd.Series) -> None:
    """Append/merge a pd.Series (DatetimeIndex → float) into per-key Parquet."""
    p = _path(parquet_dir, key)
    Path(parquet_dir).mkdir(parents=True, exist_ok=True)
    df_new = series.rename("value").to_frame()
    df_new.index.name = "date"
    if p.exists():
        df_old = pd.read_parquet(p)
        df = pd.concat([df_old, df_new]).sort_index()
        df = df[~df.index.duplicated(keep="last")]
    else:
        df = df_new
    df.to_parquet(p)


def load_series(parquet_dir: str | Path, key: str, start: date | None = None, end: date | None = None) -> pd.Series:
    p = _path(parquet_dir, key)
    if not p.exists():
        return pd.Series(dtype=float, name=key)
    df = pd.read_parquet(p)
    s = df["value"]
    s.index = pd.to_datetime(s.index)
    if start:
        s = s[s.index >= pd.Timestamp(start)]
    if end:
        s = s[s.index <= pd.Timestamp(end)]
    return s.rename(key)


def latest_value(parquet_dir: str | Path, key: str) -> tuple[pd.Timestamp | None, float | None]:
    s = load_series(parquet_dir, key)
    if s.empty:
        return None, None
    return s.index[-1], float(s.iloc[-1])


def list_available(parquet_dir: str | Path) -> list[str]:
    p = Path(parquet_dir)
    if not p.exists():
        return []
    return [f.stem for f in p.glob("*.parquet")]
