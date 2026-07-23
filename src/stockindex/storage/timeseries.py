"""지표 시계열(날짜→값)을 지표당 파일 하나(`<parquet_dir>/<key>.parquet`)로 저장하는 저장소.

`save_series()`는 append-merge 방식이라 매일 조금씩 겹치는 구간을 수집해도
중복 없이(같은 날짜는 최신값으로) 누적된다.
"""
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
    """저장된 시계열을 읽는다. 파일이 없으면 빈 Series. `start`/`end`로 기간 필터 가능."""
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
    """가장 최근 (날짜, 값)을 반환한다. 데이터가 없으면 (None, None)."""
    s = load_series(parquet_dir, key)
    if s.empty:
        return None, None
    return s.index[-1], float(s.iloc[-1])


def list_available(parquet_dir: str | Path) -> list[str]:
    """저장된 Parquet 파일들로부터 사용 가능한 지표 key 목록을 만든다."""
    p = Path(parquet_dir)
    if not p.exists():
        return []
    return [f.stem for f in p.glob("*.parquet")]
