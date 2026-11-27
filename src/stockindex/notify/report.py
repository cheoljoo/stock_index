"""`run_daily.py` 실행 결과를 HTML 메일(로그 첨부)로 보고한다.

"변경된 것"의 기준
- 지표: 직전 관측값 대비 등락, 지난 보고 이후 새 데이터가 들어왔는지(`data/last_report.json`)
- 스크리너: 직전 실행일 대비 새로 들어온 종목 / 빠진 종목
- 임계치 알림: 오늘 새로 도달한 항목
- 코드: 지난 보고 이후 커밋

메일/첨부에 들어가는 모든 텍스트는 `.env`의 비밀값을 `***`로 가린다.
"""
from __future__ import annotations

import json
import os
import re
import socket
import sqlite3
import subprocess
from datetime import date, datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from stockindex.config.loader import load_indicators, load_settings
from stockindex.core.collector import load_all_series
from stockindex.notify import mailer
from stockindex.providers import krx_openapi, krx_provider

_ROOT = Path(__file__).resolve().parents[3]
_TMPL_DIR = Path(__file__).parent / "templates"
_SECRET_NAME = re.compile(r"PASS|PW|KEY|TOKEN|SECRET|_ID$|USERNAME|SENDER")
_PROBLEM = re.compile(r"⚠|⛔|Traceback|Error|ERROR|실패|FAIL|empty \(no data|not set")


def mask_secrets(text: str) -> str:
    """이름이 비밀번호·키·토큰·계정으로 보이는 환경변수의 값을 가린다."""
    values = {v for k, v in os.environ.items() if _SECRET_NAME.search(k) and len(v) >= 4}
    for v in sorted(values, key=len, reverse=True):
        text = text.replace(v, "***")
    return text


def _query(db_path: str, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            return conn.execute(sql, args).fetchall()
    except sqlite3.Error:
        return []


def _indicator_rows(previous: dict) -> list[dict]:
    names = {k: c.display_name for k, c in load_indicators().items()}
    rows = []
    for key, s in load_all_series().items():
        if key not in names:        # ROIC 종목별 시계열 등 등록 지표가 아닌 것은 제외
            continue
        s = s.dropna()
        if s.empty:
            continue
        last, last_date = float(s.iloc[-1]), str(s.index[-1])[:10]
        prev = float(s.iloc[-2]) if len(s) > 1 else None
        pct = (last - prev) / abs(prev) * 100 if prev else None
        rows.append({"key": key, "name": names[key], "date": last_date, "value": last,
                     "pct": pct, "is_new": bool(previous) and previous.get(key) != [last_date, last]})
    return sorted(rows, key=lambda r: abs(r["pct"] or 0), reverse=True)


def _screen_diff(db_path: str, runs_table: str, rows_table: str) -> dict | None:
    """직전 실행일과 비교한 스크리너 변화."""
    runs = _query(db_path, f"SELECT * FROM {runs_table} ORDER BY snapshot_date DESC LIMIT 2")
    if not runs:
        return None

    def rows_of(d):
        return {r["ticker"]: dict(r) for r in
                _query(db_path, f"SELECT * FROM {rows_table} WHERE snapshot_date = ?", (d,))}

    cur = rows_of(runs[0]["snapshot_date"])
    prev = rows_of(runs[1]["snapshot_date"]) if len(runs) > 1 else {}
    return {
        "date": runs[0]["snapshot_date"],
        "prev_date": runs[1]["snapshot_date"] if len(runs) > 1 else None,
        "universe": runs[0]["universe_size"],
        "full": bool(runs[0]["is_full_kospi200"]),
        "count": len(cur), "prev_count": len(prev),
        "added": [cur[t] for t in cur if t not in prev],
        "removed": [prev[t] for t in prev if t not in cur],
        "rows": list(cur.values()),
    }


def _problem_lines(log_text: str) -> list[str]:
    """로그에서 확인이 필요한 줄. 수집 결과 줄에는 지표 이름이 없으므로 바로 앞 지표를 붙인다."""
    found, key = [], None
    for line in (ln.strip() for ln in log_text.splitlines()):
        m = re.match(r"\[collector\] fetching (\S+)", line)
        if m:
            key = m.group(1)
        elif _PROBLEM.search(line):
            found.append(f"{key}: {line}" if key and line.startswith("->") else line)
    return list(dict.fromkeys(found))[:30]


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", "-C", str(_ROOT), *args], capture_output=True, text=True,
                              timeout=20).stdout.strip()
    except Exception:
        return ""


def _state_path() -> Path:
    return _ROOT / "data" / "last_report.json"


def _calls(path: Path) -> int:
    try:
        st = json.loads(path.read_text())
        return st["calls"] if st["date"] == date.today().isoformat() else 0
    except Exception:
        return 0


def build_context(log_text: str, ok: bool, elapsed: float | None) -> dict:
    settings = load_settings()
    db = settings.storage.db_path
    try:
        previous = json.loads(_state_path().read_text(encoding="utf-8"))
    except Exception:
        previous = {}

    flow = _screen_diff(db, "screen_runs", "investor_flow_screen")
    if flow:
        for key in ("rows", "added", "removed"):
            flow[key].sort(key=lambda r: (r["twin_buy_streak"], r["foreign_only_buy_streak"]), reverse=True)
    own = _screen_diff(db, "ownership_screen_runs", "ownership_screen")
    if own:
        for key in ("rows", "added", "removed"):
            own[key].sort(key=lambda r: r["change_pct_points"], reverse=True)

    head = _git("rev-parse", "--short", "HEAD")
    old_head = previous.get("head")
    commits = _git("log", "--oneline", f"{old_head}..HEAD") if old_head else _git("log", "--oneline", "-3")
    cache = _ROOT / "data" / "krx_cache"
    return {
        "ok": ok,
        "now": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "host": socket.gethostname(),
        "elapsed_min": None if elapsed is None else round(elapsed / 60, 1),
        "indicators": _indicator_rows(previous.get("series", {})),
        "alerts": [dict(r) for r in _query(
            db, "SELECT indicator, level, value FROM alert_history WHERE triggered_date = ?",
            (date.today().isoformat(),))],
        "flow": flow,
        "own": own,
        "problems": _problem_lines(log_text),
        "krx_calls": _calls(cache / "calls_today.json"),
        "openapi_calls": _calls(cache / "openapi" / "calls_today.json"),
        "krx_stop": krx_provider.stop_reason() or (None if krx_openapi.available() else "Open API 사용 불가"),
        "head": head,
        "commits": commits.splitlines()[:15],
        "dirty": [ln for ln in _git("status", "--porcelain").splitlines()][:15],
        "site_url": settings.site_url,
    }


def render_html(ctx: dict) -> str:
    env = Environment(loader=FileSystemLoader(str(_TMPL_DIR)), autoescape=True)
    return mask_secrets(env.get_template("daily_report.html.j2").render(**ctx))


def _save_state(ctx: dict) -> None:
    _state_path().write_text(json.dumps({
        "head": ctx["head"],
        "series": {r["key"]: [r["date"], r["value"]] for r in ctx["indicators"]},
    }), encoding="utf-8")


def send_report(log_text: str, ok: bool = True, elapsed: float | None = None, send: bool = True) -> Path:
    """보고서를 만들어 메일로 보낸다. 만든 HTML은 `logs/last_report.html`에도 남긴다.

    `send=False`면 파일만 만든다. 발송에 실패하면 예외를 던진다.
    """
    settings = load_settings()
    log_text = mask_secrets(log_text)
    ctx = build_context(log_text, ok, elapsed)
    html = render_html(ctx)
    out = _ROOT / "logs" / "last_report.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(html, encoding="utf-8")
    if not (send and settings.report.enabled and settings.report.to):
        return out

    password = mailer.smtp_password(settings.smtp)
    if not password:
        raise RuntimeError("SMTP 비밀번호가 없습니다 (SMTP_PASSWORD 또는 GMAIL_APP_PASSWORD)")

    msg = MIMEMultipart("mixed")
    status = "성공" if ok else "실패"
    msg["Subject"] = (f"[stock_index] {date.today()} 일일 수집 {status} — 알림 {len(ctx['alerts'])}건"
                      + (f", 확인 필요 {len(ctx['problems'])}줄" if ctx["problems"] else ""))
    msg["From"] = settings.smtp.from_
    msg["To"] = ", ".join(settings.report.to)
    msg.attach(MIMEText(html, "html", "utf-8"))
    att = MIMEApplication(log_text.encode("utf-8"), _subtype="octet-stream")
    att.add_header("Content-Disposition", "attachment", filename=f"run_daily_{date.today():%Y%m%d}.log")
    msg.attach(att)
    mailer.deliver(settings.smtp, password, settings.report.to, msg)
    _save_state(ctx)
    print(f"[report] 결과 메일 발송: {msg['Subject']}")
    return out
