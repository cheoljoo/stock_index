"""임계치 도달 알림을 HTML 이메일로 발송한다 (`run_daily.py`가 매일 호출).

`SMTP_PASSWORD`(.env)가 비어있으면 실제 발송 없이 수신자 목록만 출력하고 넘어간다 —
아직 메일 설정을 하지 않았어도 나머지 파이프라인(수집·알림 기록)은 정상 동작한다.
"""
from __future__ import annotations
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from stockindex.config.loader import load_settings


_TMPL_DIR = Path(__file__).parent / "templates"


def render_alert_html(triggered: list[dict], site_url: str) -> str:
    """`templates/alert.html.j2`에 도달 항목(triggered)을 채워 HTML 본문을 렌더링한다."""
    env = Environment(loader=FileSystemLoader(str(_TMPL_DIR)), autoescape=True)
    tmpl = env.get_template("alert.html.j2")
    return tmpl.render(triggered=triggered, site_url=site_url)


def send_alert(triggered: list[dict]) -> None:
    """`run_alerts()`가 반환한 도달 항목들을 모아 해당 항목의 수신자 전원에게 한 통으로 보낸다.

    Args:
        triggered: [{"indicator", "level", "value", "recipients": [...]}, ...].
                   비어있으면 아무 것도 하지 않는다.
    """
    if not triggered:
        return
    settings = load_settings()
    smtp_cfg = settings.smtp
    site_url = settings.site_url

    # Collect all unique recipients
    all_recipients: set[str] = set()
    for item in triggered:
        all_recipients.update(item.get("recipients", []))
    if not all_recipients:
        return

    html = render_alert_html(triggered, site_url)
    subject = f"[주식지표 알림] {len(triggered)}개 임계치 도달"

    password = os.environ.get(smtp_cfg.password_env, "")
    if not password:
        print(f"[mailer] SMTP password env '{smtp_cfg.password_env}' not set — skipping mail")
        print(f"[mailer] Would send to: {all_recipients}")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_cfg.from_
    msg["To"] = ", ".join(sorted(all_recipients))
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP(smtp_cfg.host, smtp_cfg.port) as server:
        server.ehlo()
        server.starttls()
        server.login(smtp_cfg.user, password)
        server.sendmail(smtp_cfg.from_, list(all_recipients), msg.as_string())
    print(f"[mailer] Sent alert to {all_recipients}")
