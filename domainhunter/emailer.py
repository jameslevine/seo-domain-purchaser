"""Render the buy-list to HTML (Jinja2) and send it over SMTP (Gmail app password)."""

from __future__ import annotations

import logging
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import PROJECT_ROOT, Credentials
from .models import Candidate

log = logging.getLogger(__name__)

TEMPLATE_DIR = PROJECT_ROOT / "templates"


def render_email(
    candidates: list[Candidate],
    *,
    list_slug: str,
    subject_prefix: str,
    preferred_backorder: list[str],
    filtered_total: int | None = None,
) -> str:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "j2"]),
    )
    template = env.get_template("email.html.j2")
    return template.render(
        candidates=candidates,
        count=len(candidates),
        list_slug=list_slug,
        subject_prefix=subject_prefix,
        preferred_backorder=preferred_backorder,
        filtered_total=filtered_total,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )


def write_preview(html: str, out_dir: Path | None = None) -> Path:
    """Write the rendered email to output/ for local inspection (used by --dry-run)."""
    out_dir = out_dir or (PROJECT_ROOT / "output")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"buylist-{datetime.now().strftime('%Y%m%d-%H%M%S')}.html"
    path.write_text(html, encoding="utf-8")
    return path


def send_email(html: str, *, subject: str, creds: Credentials) -> None:
    if not creds.smtp_password or not creds.email_to:
        raise RuntimeError("SMTP_PASSWORD / EMAIL_TO not configured — cannot send.")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = creds.email_from
    msg["To"] = creds.email_to
    msg.attach(MIMEText("This email requires an HTML-capable client.", "plain"))
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(creds.smtp_host, creds.smtp_port, timeout=30) as server:
        server.starttls()
        server.login(creds.smtp_username, creds.smtp_password)
        server.sendmail(creds.email_from, [creds.email_to], msg.as_string())
    log.info("Sent buy-list email to %s", creds.email_to)
