"""Email delivery service: SMTP (primary) with SendGrid as an optional override.

Provider selection:
  - If SENDGRID_API_KEY is set → send via SendGrid REST API
  - Otherwise → send via SMTP (SMTP_HOST/PORT/USER/PASS settings)

Both paths send a multipart/mixed email with:
  - text/plain fallback body
  - text/html rich body (inline exec summary)
  - application/pdf attachment (the daily digest PDF)

Compatible with any SMTP relay (Gmail App Password, Brevo, Mailgun SMTP, etc.).
Brevo: use SMTP_HOST=smtp-relay.brevo.com, SMTP_PORT=587 with STARTTLS.
"""
import logging
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

from backend.config import settings

logger = logging.getLogger(__name__)


def send_digest_email(
    recipients: list[str],
    date_str: str,
    exec_summary: str,
    pdf_path: Optional[str],
    run_id: int,
) -> bool:
    """Send the daily digest email with inline exec summary and PDF attachment.

    Returns True on success, False on any delivery failure.
    """
    if not recipients:
        logger.warning("No email recipients configured.")
        return False

    subject = f"Frontier AI Radar — Daily Digest ({date_str})"
    # Deep-link to the specific run on the dashboard.
    dashboard_url = f"{settings.frontend_url}/runs/{run_id}"

    html_body = _build_email_html(exec_summary, date_str, dashboard_url)
    text_body = _build_email_text(exec_summary, date_str, dashboard_url)

    try:
        # Use SendGrid if API key is configured, otherwise fall back to SMTP.
        if settings.sendgrid_api_key:
            return _send_via_sendgrid(recipients, subject, html_body, text_body, pdf_path)
        else:
            return _send_via_smtp(recipients, subject, html_body, text_body, pdf_path)
    except Exception as e:
        logger.error(f"Email send failed: {e}")
        return False


def _build_email_html(exec_summary: str, date_str: str, dashboard_url: str) -> str:
    """Build the HTML email body with inline exec_summary bullet points."""
    bullets = exec_summary.replace("\n- ", "</li><li>").replace("- ", "<li>", 1)
    return f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width"></head>
<body style="font-family: -apple-system, Arial, sans-serif; max-width: 700px; margin: 0 auto; padding: 24px; color: #1a1a1a;">
  <div style="background: linear-gradient(135deg, #1e3a5f, #0f5132); padding: 24px; border-radius: 8px; margin-bottom: 24px;">
    <h1 style="color: white; margin: 0; font-size: 24px;">Frontier AI Radar</h1>
    <p style="color: #a8d8b9; margin: 4px 0 0; font-size: 14px;">Daily Intelligence Digest — {date_str}</p>
  </div>
  <h2 style="color: #1e3a5f; font-size: 18px;">Today's Top Developments</h2>
  <ul style="padding-left: 20px; line-height: 1.8;">
    {bullets}
  </ul>
  <div style="margin-top: 24px; padding: 16px; background: #f0f4f8; border-radius: 6px;">
    <p style="margin: 0; font-size: 14px; color: #555;">
      Full digest attached as PDF.
      <a href="{dashboard_url}" style="color: #1e3a5f;">View on dashboard →</a>
    </p>
  </div>
  <p style="font-size: 11px; color: #999; margin-top: 24px;">Frontier AI Radar — automated intelligence system</p>
</body>
</html>
"""


def _build_email_text(exec_summary: str, date_str: str, dashboard_url: str) -> str:
    """Build the plain-text fallback email body (shown when HTML is blocked)."""
    return f"""Frontier AI Radar — Daily Digest ({date_str})

TODAY'S TOP DEVELOPMENTS:
{exec_summary}

Full digest attached as PDF.
View on dashboard: {dashboard_url}
"""


def _send_via_smtp(
    recipients: list[str],
    subject: str,
    html_body: str,
    text_body: str,
    pdf_path: Optional[str],
) -> bool:
    """Send email via SMTP using STARTTLS.

    Constructs a multipart/mixed message with:
      - multipart/alternative inner part (text + HTML)
      - application/pdf attachment (when pdf_path exists)

    Compatible with Gmail App Passwords, Brevo relay, and most SMTP providers.
    """
    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = settings.email_from or settings.smtp_user
    msg["To"] = ", ".join(recipients)

    # Inner alternative part: clients show HTML if supported, text otherwise.
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(text_body, "plain"))
    alt.attach(MIMEText(html_body, "html"))
    msg.attach(alt)

    # Attach PDF if it exists on disk.
    if pdf_path and Path(pdf_path).exists():
        with open(pdf_path, "rb") as f:
            pdf_data = f.read()
        attachment = MIMEApplication(pdf_data, _subtype="pdf")
        attachment.add_header(
            "Content-Disposition",
            "attachment",
            filename=Path(pdf_path).name,
        )
        msg.attach(attachment)

    # Connect, upgrade to TLS, authenticate, send.
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        server.ehlo()
        server.starttls()
        server.login(settings.smtp_user, settings.smtp_pass)
        server.sendmail(msg["From"], recipients, msg.as_string())

    logger.info(f"Email sent to {len(recipients)} recipients")
    return True


def _send_via_sendgrid(
    recipients: list[str],
    subject: str,
    html_body: str,
    text_body: str,
    pdf_path: Optional[str],
) -> bool:
    """Send email via the SendGrid v3 Mail Send API.

    Used when SENDGRID_API_KEY is set in .env (overrides SMTP).
    PDF is base64-encoded and included as an inline attachment.
    """
    import base64
    import httpx

    # Build attachments list — empty if no PDF file exists.
    attachments = []
    if pdf_path and Path(pdf_path).exists():
        with open(pdf_path, "rb") as f:
            pdf_b64 = base64.b64encode(f.read()).decode()
        attachments.append({
            "content": pdf_b64,
            "type": "application/pdf",
            "filename": Path(pdf_path).name,
            "disposition": "attachment",
        })

    payload = {
        "personalizations": [{"to": [{"email": r} for r in recipients]}],
        "from": {"email": settings.email_from or settings.smtp_user},
        "subject": subject,
        "content": [
            {"type": "text/plain", "value": text_body},
            {"type": "text/html", "value": html_body},
        ],
        "attachments": attachments,
    }

    resp = httpx.post(
        "https://api.sendgrid.com/v3/mail/send",
        json=payload,
        headers={"Authorization": f"Bearer {settings.sendgrid_api_key}"},
    )
    resp.raise_for_status()
    logger.info(f"Email sent via SendGrid to {len(recipients)} recipients")
    return True
