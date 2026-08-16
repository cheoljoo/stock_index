"""SQLite 저장소: 지표 메타데이터, 임계치 알림 이력, 포트폴리오 스냅샷을 보관한다.

시계열 본체는 Parquet(`storage/timeseries.py`)에 저장하고, 여기서는 "구조화된
메타/이력" 데이터만 다룬다. `alert_history`의 (indicator, level, triggered_date)
UNIQUE 인덱스가 동일 임계치의 중복 메일 발송을 막는 핵심 장치다.
"""
from __future__ import annotations
import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path


def init_db(db_path: str | Path) -> None:
    """필요한 테이블(indicators, alert_history, portfolio_snapshots)을 없으면 생성한다."""
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

            CREATE TABLE IF NOT EXISTS screen_runs (
                snapshot_date TEXT PRIMARY KEY,
                universe_size INTEGER,
                is_full_kospi200 INTEGER,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS investor_flow_screen (
                ticker TEXT NOT NULL,
                name TEXT,
                snapshot_date TEXT NOT NULL,
                twin_buy_streak INTEGER,
                twin_sell_streak INTEGER,
                foreign_only_buy_streak INTEGER,
                latest_close REAL,
                created_at TEXT DEFAULT (datetime('now')),
                PRIMARY KEY (ticker, snapshot_date)
            );

            CREATE TABLE IF NOT EXISTS ownership_screen_runs (
                snapshot_date TEXT PRIMARY KEY,
                universe_size INTEGER,
                is_full_kospi200 INTEGER,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS ownership_screen (
                ticker TEXT NOT NULL,
                name TEXT,
                snapshot_date TEXT NOT NULL,
                change_pct_points REAL,
                up_day_ratio REAL,
                max_daily_jump REAL,
                is_steady_increase INTEGER,
                is_spike INTEGER,
                latest_ratio REAL,
                latest_close REAL,
                created_at TEXT DEFAULT (datetime('now')),
                PRIMARY KEY (ticker, snapshot_date)
            );
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
    """지표 메타(표시명·provider·symbol 등)를 삽입하거나, 있으면 갱신한다."""
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
    """최근 `days`일간 발송(기록)된 알림 이력을 최신순으로 반환한다."""
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
    """국부펀드 자산배분 스냅샷(자산군별 비중)을 저장한다. 동일 스냅샷은 덮어쓴다."""
    with _connect(db_path) as conn:
        for row in rows:
            conn.execute(
                """INSERT INTO portfolio_snapshots(fund_key, snapshot_date, asset_class, weight_pct, amount_bn)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT(fund_key, snapshot_date, asset_class) DO UPDATE
                   SET weight_pct=excluded.weight_pct, amount_bn=excluded.amount_bn""",
                (fund_key, snapshot_date.isoformat(), row.get("asset_class"), row.get("weight_pct"), row.get("amount_bn")),
            )


def save_investor_flow_screen(
    db_path: str | Path,
    snapshot_date: date,
    results: list,
) -> None:
    """스크리너 결과(`core.screener.FlowScreenResult` 목록)를 저장한다.

    같은 (ticker, snapshot_date)는 덮어쓴다 — 하루 한 번 cron이 그 날의 최신 스냅샷만
    남기면 되므로, 과거 이력을 계속 쌓기보다 최근 스냅샷 위주로 조회하는 용도다.
    """
    with _connect(db_path) as conn:
        for r in results:
            conn.execute(
                """INSERT INTO investor_flow_screen
                       (ticker, name, snapshot_date, twin_buy_streak, twin_sell_streak,
                        foreign_only_buy_streak, latest_close)
                   VALUES(?,?,?,?,?,?,?)
                   ON CONFLICT(ticker, snapshot_date) DO UPDATE SET
                       name=excluded.name,
                       twin_buy_streak=excluded.twin_buy_streak,
                       twin_sell_streak=excluded.twin_sell_streak,
                       foreign_only_buy_streak=excluded.foreign_only_buy_streak,
                       latest_close=excluded.latest_close""",
                (r.ticker, r.name, snapshot_date.isoformat(), r.twin_buy_streak,
                 r.twin_sell_streak, r.foreign_only_buy_streak, r.latest_close),
            )


def save_ownership_screen(
    db_path: str | Path,
    snapshot_date: date,
    results: list,
) -> None:
    """지분율 스크리너 결과(`core.screener.OwnershipScreenResult` 목록)를 저장한다.

    `save_investor_flow_screen`과 같은 덮어쓰기 방식 — 최근 스냅샷만 유지한다.
    """
    with _connect(db_path) as conn:
        for r in results:
            conn.execute(
                """INSERT INTO ownership_screen
                       (ticker, name, snapshot_date, change_pct_points, up_day_ratio,
                        max_daily_jump, is_steady_increase, is_spike, latest_ratio, latest_close)
                   VALUES(?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(ticker, snapshot_date) DO UPDATE SET
                       name=excluded.name,
                       change_pct_points=excluded.change_pct_points,
                       up_day_ratio=excluded.up_day_ratio,
                       max_daily_jump=excluded.max_daily_jump,
                       is_steady_increase=excluded.is_steady_increase,
                       is_spike=excluded.is_spike,
                       latest_ratio=excluded.latest_ratio,
                       latest_close=excluded.latest_close""",
                (r.ticker, r.name, snapshot_date.isoformat(), r.change_pct_points, r.up_day_ratio,
                 r.max_daily_jump, int(r.is_steady_increase), int(r.is_spike), r.latest_ratio, r.latest_close),
            )


def save_ownership_screen_run(
    db_path: str | Path, snapshot_date: date, universe_size: int, is_full_kospi200: bool,
) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """INSERT INTO ownership_screen_runs(snapshot_date, universe_size, is_full_kospi200)
               VALUES(?,?,?)
               ON CONFLICT(snapshot_date) DO UPDATE SET
                   universe_size=excluded.universe_size,
                   is_full_kospi200=excluded.is_full_kospi200""",
            (snapshot_date.isoformat(), universe_size, int(is_full_kospi200)),
        )


def get_latest_ownership_screen_run(db_path: str | Path) -> dict | None:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM ownership_screen_runs ORDER BY snapshot_date DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


def get_latest_ownership_screen(db_path: str | Path) -> list[dict]:
    """`ownership_screen`에 저장된 가장 최근 스냅샷 날짜의 전체 종목을 반환한다."""
    with _connect(db_path) as conn:
        latest = conn.execute(
            "SELECT MAX(snapshot_date) AS d FROM ownership_screen"
        ).fetchone()["d"]
        if not latest:
            return []
        rows = conn.execute(
            "SELECT * FROM ownership_screen WHERE snapshot_date=? "
            "ORDER BY change_pct_points DESC",
            (latest,),
        ).fetchall()
    return [dict(r) for r in rows]


def save_screen_run(
    db_path: str | Path, snapshot_date: date, universe_size: int, is_full_kospi200: bool,
) -> None:
    """스크리너가 그 날 실제로 몇 종목을 스캔했고, 정식 KOSPI200 전종목이었는지를 기록한다.

    `get_index_portfolio_deposit_file`(pykrx)이 KRX API 변경으로 불안정해, 대시보드가
    "지금 보는 결과가 KOSPI200 전체인지 대형주 근사 리스트인지"를 알 수 있어야 한다.
    """
    with _connect(db_path) as conn:
        conn.execute(
            """INSERT INTO screen_runs(snapshot_date, universe_size, is_full_kospi200)
               VALUES(?,?,?)
               ON CONFLICT(snapshot_date) DO UPDATE SET
                   universe_size=excluded.universe_size,
                   is_full_kospi200=excluded.is_full_kospi200""",
            (snapshot_date.isoformat(), universe_size, int(is_full_kospi200)),
        )


def get_latest_screen_run(db_path: str | Path) -> dict | None:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM screen_runs ORDER BY snapshot_date DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


def get_latest_investor_flow_screen(db_path: str | Path) -> list[dict]:
    """`investor_flow_screen`에 저장된 가장 최근 스냅샷 날짜의 전체 종목을 반환한다."""
    with _connect(db_path) as conn:
        latest = conn.execute(
            "SELECT MAX(snapshot_date) AS d FROM investor_flow_screen"
        ).fetchone()["d"]
        if not latest:
            return []
        rows = conn.execute(
            "SELECT * FROM investor_flow_screen WHERE snapshot_date=? "
            "ORDER BY twin_buy_streak DESC",
            (latest,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_portfolio_history(db_path: str | Path, fund_key: str) -> list[dict]:
    """특정 펀드(fund_key)의 스냅샷 이력을 날짜순으로 반환한다."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM portfolio_snapshots WHERE fund_key=? ORDER BY snapshot_date",
            (fund_key,),
        ).fetchall()
    return [dict(r) for r in rows]
