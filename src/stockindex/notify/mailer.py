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


def render_flow_screen_html(results: list, min_days: int, site_url: str) -> str:
    """`templates/flow_screen.html.j2`에 스크리너 결과(`core.screener.FlowScreenResult` 목록)를 채워 렌더링한다."""
    env = Environment(loader=FileSystemLoader(str(_TMPL_DIR)), autoescape=True)
    tmpl = env.get_template("flow_screen.html.j2")
    return tmpl.render(results=results, min_days=min_days, site_url=site_url)


def smtp_password(smtp_cfg) -> str:
    """설정된 환경변수의 비밀번호. 비어 있고 같은 계정의 Gmail 앱 비밀번호(GMAIL_APP_PASSWORD)가 있으면 그것을 쓴다."""
    password = os.environ.get(smtp_cfg.password_env, "")
    if not password and os.environ.get("GMAIL_SENDER", "") == smtp_cfg.user:
        password = os.environ.get("GMAIL_APP_PASSWORD", "")
    return password


def deliver(smtp_cfg, password: str, recipients, msg) -> None:
    with smtplib.SMTP(smtp_cfg.host, smtp_cfg.port, timeout=60) as server:
        server.ehlo()
        server.starttls()
        server.login(smtp_cfg.user, password)
        server.sendmail(smtp_cfg.from_, list(recipients), msg.as_string())


def _send_html_mail(subject: str, html: str, recipients: set[str]) -> None:
    """공통 SMTP 발송 경로. `SMTP_PASSWORD` 미설정 시 발송 없이 수신자만 출력한다."""
    if not recipients:
        return
    settings = load_settings()
    smtp_cfg = settings.smtp

    password = smtp_password(smtp_cfg)
    if not password:
        print(f"[mailer] SMTP password env '{smtp_cfg.password_env}' not set — skipping mail")
        print(f"[mailer] Would send to: {recipients}")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_cfg.from_
    msg["To"] = ", ".join(sorted(recipients))
    msg.attach(MIMEText(html, "html", "utf-8"))

    deliver(smtp_cfg, password, recipients, msg)
    print(f"[mailer] Sent mail to {recipients}")


def send_alert(triggered: list[dict]) -> None:
    """`run_alerts()`가 반환한 도달 항목들을 모아 해당 항목의 수신자 전원에게 한 통으로 보낸다.

    Args:
        triggered: [{"indicator", "level", "value", "recipients": [...]}, ...].
                   비어있으면 아무 것도 하지 않는다.
    """
    if not triggered:
        return
    settings = load_settings()

    all_recipients: set[str] = set()
    for item in triggered:
        all_recipients.update(item.get("recipients", []))

    html = render_alert_html(triggered, settings.site_url)
    subject = f"[주식지표 알림] {len(triggered)}개 임계치 도달"
    _send_html_mail(subject, html, all_recipients)


def send_flow_screen_digest(results: list, min_days: int, recipients: list[str]) -> None:
    """`core.screener.screen_kospi200()` 결과 중 `min_days` 이상인 종목을 한 통으로 발송한다.

    Args:
        results: `screen_kospi200()`의 전체 반환값 (min_days 미달 종목도 섞여 있을 수 있음 —
                 여기서 다시 걸러 화면 목록을 좁힌다).
    """
    notable = [
        r for r in results
        if max(r.twin_buy_streak, r.twin_sell_streak, r.foreign_only_buy_streak) >= min_days
    ]
    if not notable:
        return
    settings = load_settings()
    html = render_flow_screen_html(notable, min_days, settings.site_url)
    subject = f"[수급 스크리너] {len(notable)}개 종목 {min_days}일 이상 연속 수급"
    _send_html_mail(subject, html, set(recipients))
