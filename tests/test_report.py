"""일일 결과 보고(HTML 메일) 테스트 — 메일은 보내지 않는다."""
from stockindex.notify import report
from stockindex.storage import db as _db


def test_mask_secrets(monkeypatch):
    monkeypatch.setenv("KRX_PW", "s3cret-value")
    monkeypatch.setenv("KRX_ID", "someuser")
    monkeypatch.setenv("PSNCS_PORT", "2222")                # 비밀 이름이 아니면 그대로 둔다
    out = report.mask_secrets("id=someuser pw=s3cret-value port=2222")
    assert out == "id=*** pw=*** port=2222"


def test_screen_diff_added_removed(tmp_path):
    db = str(tmp_path / "m.db")
    _db.init_db(db)
    import sqlite3
    with sqlite3.connect(db) as c:
        for d, tickers in (("2026-01-01", ["A", "B"]), ("2026-01-02", ["B", "C"])):
            c.execute("INSERT INTO screen_runs(snapshot_date, universe_size, is_full_kospi200) VALUES (?,?,?)", (d, 201, 1))
            for t in tickers:
                c.execute("INSERT INTO investor_flow_screen(ticker, name, snapshot_date) VALUES (?,?,?)", (t, t, d))
    diff = report._screen_diff(db, "screen_runs", "investor_flow_screen")
    assert [r["name"] for r in diff["added"]] == ["C"]
    assert [r["name"] for r in diff["removed"]] == ["A"]
    assert diff["prev_date"] == "2026-01-01" and diff["count"] == 2


def test_render_has_dark_and_light_theme_and_escapes():
    ctx = dict(ok=False, now="n", host="h", elapsed_min=1.0, indicators=[], alerts=[], flow=None, own=None,
               problems=["Traceback <boom>"], krx_calls=0, openapi_calls=0, krx_stop=None, head="abc",
               commits=[], dirty=[], site_url="")
    html = report.render_html(ctx)
    assert "prefers-color-scheme: dark" in html and 'content="light dark"' in html
    assert "실패" in html and "&lt;boom&gt;" in html


def test_problem_lines_name_the_indicator():
    log = """[collector] fetching gold (GC=F) via yfinance...
  -> 12 rows, latest=1.0
[collector] fetching nps_portfolio (nps) via portfolio...
  -> empty (no data returned)
[mailer] SMTP password env 'SMTP_PASSWORD' not set — skipping mail
"""
    assert report._problem_lines(log) == [
        "nps_portfolio: -> empty (no data returned)",
        "[mailer] SMTP password env 'SMTP_PASSWORD' not set — skipping mail",
    ]
