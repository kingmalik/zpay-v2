"""
Gmail API email service for sending pay stub PDFs.

Uses the Gmail HTTP API (not SMTP) so it works on Railway and other cloud
providers that block outbound SMTP ports 465/587.

Required Railway env vars:
    GMAIL_CLIENT_ID        — OAuth2 client ID from Google Cloud Console
    GMAIL_CLIENT_SECRET    — OAuth2 client secret
    GMAIL_REFRESH_TOKEN_ACUMEN  — refresh token for noreply.acumenpay@gmail.com
    GMAIL_REFRESH_TOKEN_MAZ     — refresh token for noreply.mazpay@gmail.com
    GMAIL_USER_ACUMEN      — noreply.acumenpay@gmail.com  (sends paystubs for Acumen & FirstAlt)
    GMAIL_USER_MAZ         — noreply.mazpay@gmail.com  (sends paystubs for Maz & EverDriven)

Run scripts/get_gmail_token.py once per Gmail account to generate refresh tokens.
"""

import os
import re
import base64
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
from pathlib import Path

from backend.utils.test_mode import redirect_email, test_subject


# Map company name keywords → (user env var, refresh token env var)
COMPANY_ACCOUNTS = {
    "acumen":    ("GMAIL_USER_ACUMEN", "GMAIL_REFRESH_TOKEN_ACUMEN"),
    "maz":       ("GMAIL_USER_MAZ",    "GMAIL_REFRESH_TOKEN_MAZ"),
    "everdriven": ("GMAIL_USER_MAZ",   "GMAIL_REFRESH_TOKEN_MAZ"),
    "firstalt":  ("GMAIL_USER_ACUMEN", "GMAIL_REFRESH_TOKEN_ACUMEN"),
}


def _get_gmail_service(company: str):
    """Return (gmail_service, from_email) for the given company."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    key = company.lower().replace(" ", "").replace("international", "")
    user_var = "GMAIL_USER"
    token_var = "GMAIL_REFRESH_TOKEN"
    for prefix, (u, t) in COMPANY_ACCOUNTS.items():
        if prefix in key:
            user_var, token_var = u, t
            break

    client_id     = os.environ.get("GMAIL_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GMAIL_CLIENT_SECRET", "").strip()
    refresh_token = os.environ.get(token_var, "").strip()
    from_email    = os.environ.get(user_var, os.environ.get("GMAIL_USER", "")).strip()

    if not all([client_id, client_secret, refresh_token, from_email]):
        missing = [k for k, v in {
            "GMAIL_CLIENT_ID": client_id,
            "GMAIL_CLIENT_SECRET": client_secret,
            token_var: refresh_token,
            user_var: from_email,
        }.items() if not v]
        raise ValueError(f"Gmail API credentials not configured. Missing: {', '.join(missing)}")

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/gmail.send"],
    )
    # Auto-refresh the access token
    creds.refresh(Request())

    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    return service, from_email


# Company-specific email branding
COMPANY_BRAND = {
    "acumen": {
        "name": "Acumen International",
        "banner_bg": "#4a1525",
        "banner_accent": "#9b2c3d",
        "label_color": "#c47a88",
        "subtitle_color": "#d4959f",
        "accent_bar": "#9b2c3d",
        "footer_text": "Acumen International Payroll",
    },
    "maz": {
        "name": "Maz Services",
        "banner_bg": "#0f1d3a",
        "banner_accent": "#1e3a6e",
        "label_color": "#6b82b0",
        "subtitle_color": "#8da0c9",
        "accent_bar": "#1e3a6e",
        "footer_text": "Maz Services Payroll",
    },
    "firstalt": {
        "name": "FirstAlt",
        "banner_bg": "#4a1525",
        "banner_accent": "#9b2c3d",
        "label_color": "#c47a88",
        "subtitle_color": "#d4959f",
        "accent_bar": "#9b2c3d",
        "footer_text": "FirstAlt Payroll — Powered by Acumen International",
    },
    "everdriven": {
        "name": "EverDriven",
        "banner_bg": "#0f1d3a",
        "banner_accent": "#1e3a6e",
        "label_color": "#6b82b0",
        "subtitle_color": "#8da0c9",
        "accent_bar": "#1e3a6e",
        "footer_text": "EverDriven Payroll — Powered by Maz Services",
    },
}

_DEFAULT_BRAND = {
    "name": "Pay Stub",
    "banner_bg": "#0f172a",
    "banner_accent": "#667eea",
    "label_color": "#64748b",
    "subtitle_color": "#94a3b8",
    "accent_bar": "#667eea",
    "footer_text": "Payroll Department",
}


def _get_brand(company: str) -> dict:
    """Resolve branding for a company name."""
    key = company.lower().replace(" ", "").replace("international", "")
    for prefix, brand in COMPANY_BRAND.items():
        if prefix in key:
            return brand
    return _DEFAULT_BRAND


def _body_to_html(body: str, company: str, subject: str) -> str:
    body = body.strip()
    if body.startswith("<"):
        content_html = body
    else:
        paragraphs = body.split("\n\n")
        content_html = "".join(
            f'<p style="margin:0 0 18px 0">{p.replace(chr(10), "<br>")}</p>'
            for p in paragraphs if p.strip()
        )

    brand = _get_brand(company)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
</head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;">
  <div style="max-width:600px;margin:32px auto;background:#ffffff;border-radius:10px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08);">
    <div style="background:{brand['banner_bg']};padding:28px 36px;border-bottom:3px solid {brand['accent_bar']};">
      <div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.12em;color:{brand['label_color']};margin-bottom:6px;">Pay Stub</div>
      <div style="font-size:20px;font-weight:700;color:#f8fafc;letter-spacing:-0.3px;">{subject}</div>
      <div style="font-size:13px;color:{brand['subtitle_color']};margin-top:4px;">{company}</div>
    </div>
    <div style="padding:36px;font-size:15px;color:#374151;line-height:1.8;">
      {content_html}
    </div>
    <div style="height:1px;background:#e2e8f0;margin:0 36px;"></div>
    <div style="padding:20px 36px;font-size:12px;color:#94a3b8;line-height:1.6;">
      Your pay stub PDF is attached to this email.<br>
      Questions? Reply to this email or contact your coordinator.
    </div>
    <div style="background:{brand['banner_bg']};padding:14px 36px;text-align:center;">
      <div style="font-size:11px;font-weight:600;color:{brand['label_color']};letter-spacing:0.05em;">{brand['footer_text']}</div>
    </div>
  </div>
</body>
</html>"""


def _html_to_plain(html: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"</p>|</div>|</li>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def send_paystub(
    to_email: str,
    driver_name: str,
    company: str,
    payweek: str,
    pdf_path: Path,
    person_id: int | None = None,
    payroll_batch_id: int | None = None,
    week_start: str = "",
    week_end: str = "",
    total_pay: str = "",
    ride_count: int = 0,
    db=None,
) -> None:
    """Send a pay stub PDF via Gmail API (HTTPS, not SMTP)."""
    # TEST MODE: redirect recipient email before any sending logic
    to_email = redirect_email(to_email)

    gmail_service, from_email = _get_gmail_service(company)

    # Resolve subject + body from template
    if db is not None:
        from backend.routes.email_templates import get_template, render_template, build_signature_html
        tmpl = get_template(db, person_id=person_id, batch_id=payroll_batch_id)
        ctx = {
            "driver_name": driver_name,
            "first_name": (driver_name.split() or ["Driver"])[0],
            "week_start": week_start or payweek,
            "week_end": week_end or payweek,
            "total_pay": total_pay,
            "ride_count": str(ride_count),
            "company_name": company,
            "signature_html": build_signature_html(company),
        }
        subject, body = render_template(tmpl, ctx)
    else:
        first = (driver_name.split() or ["Driver"])[0]
        subject = f"{company} — Pay Stub: {payweek}"
        body = (
            f"<p>Hi {first},</p>"
            f"<p>Please find attached your pay stub for the pay period: {payweek}.</p>"
            f"<p>If you have any questions, please reach out.</p>"
            f"<p>— {company}</p>"
        )

    # TEST MODE: prefix subject with [TEST]
    subject = test_subject(subject)

    html_email = _body_to_html(body, company=company, subject=subject)
    plain_email = _html_to_plain(html_email)

    # Build MIME message
    msg = MIMEMultipart("mixed")
    msg["From"] = from_email
    msg["To"] = to_email
    msg["Subject"] = subject

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(plain_email, "plain", "utf-8"))
    alt.attach(MIMEText(html_email, "html", "utf-8"))
    msg.attach(alt)

    with open(pdf_path, "rb") as f:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f'attachment; filename="{pdf_path.name}"')
    msg.attach(part)

    # Send via Gmail API (HTTPS, not SMTP)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    gmail_service.users().messages().send(userId="me", body={"raw": raw}).execute()
