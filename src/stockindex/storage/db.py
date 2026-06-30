from __future__ import annotations
import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path


def init_db(db_path: str | Path) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with _connect(db_path) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS indicators (
                key TEXT PRIMARY KEY,
                display_name TEXT,
                provider TEXT,
                symbol TEXT,
                unit TEXT,
                category TEXT,
                enabled INTEGER DEFAULT 1,
                last_fetched TEXT
            );

            CREATE TABLE IF NOT EXISTS alert_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                indicator TEXT NOT NULL,
                level TEXT NOT NULL,
                triggered_date TEXT NOT NULL,
                value REAL,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE UNIQUE INDEX IF NOT EXISTS ux_alert
                ON alert_history(indicator, level, triggered_date);

            CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fund_key TEXT NOT NULL,
                snapshot_date TEXT NOT NULL,
                asset_class TEXT,
                weight_pct REAL,
                amount_bn REAL,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE UNIQUE INDEX IF NOT EXISTS ux_portfolio
                ON portfolio_snapshots(fund_key, snapshot_date, asset_class);
        """)


@contextmanager
def _connect(db_path: str | Path):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def upsert_indicator_meta(db_path: str | Path, key: str, **fields) -> None:
    cols = ["key"] + list(fields.keys())
    vals = [key] + list(fields.values())
    placeholders = ",".join("?" * len(cols))
    updates = ",".join(f"{c}=excluded.{c}" for c in cols if c != "key")
    sql = (
        f"INSERT INTO indicators({','.join(cols)}) VALUES({placeholders}) "
        f"ON CONFLICT(key) DO UPDATE SET {updates}"
    )
    with _connect(db_path) as conn:
        conn.execute(sql, vals)


def record_alert(
    db_path: str | Path,
    indicator: str,
    level: str,
    triggered_date: date,
    value: float | None,
) -> bool:
    """Returns True if newly inserted (not a duplicate)."""
    with _connect(db_path) as conn:
        try:
            conn.execute(
                "INSERT INTO alert_history(indicator, level, triggered_date, value) VALUES(?,?,?,?)",
                (indicator, level, triggered_date.isoformat(), value),
            )
            return True
        except sqlite3.IntegrityError:
            return False


def recent_alerts(db_path: str | Path, days: int = 7) -> list[dict]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM alert_history WHERE triggered_date >= date('now', ?) ORDER BY triggered_date DESC",
            (f"-{days} days",),
        ).fetchall()
    return [dict(r) for r in rows]


def save_portfolio_snapshot(
    db_path: str | Path,
    fund_key: str,
    snapshot_date: date,
    rows: list[dict],
) -> None:
    with _connect(db_path) as conn:
        for row in rows:
            conn.execute(
                """INSERT INTO portfolio_snapshots(fund_key, snapshot_date, asset_class, weight_pct, amount_bn)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT(fund_key, snapshot_date, asset_class) DO UPDATE
                   SET weight_pct=excluded.weight_pct, amount_bn=excluded.amount_bn""",
                (fund_key, snapshot_date.isoformat(), row.get("asset_class"), row.get("weight_pct"), row.get("amount_bn")),
            )


def get_portfolio_history(db_path: str | Path, fund_key: str) -> list[dict]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM portfolio_snapshots WHERE fund_key=? ORDER BY snapshot_date",
            (fund_key,),
        ).fetchall()
    return [dict(r) for r in rows]
