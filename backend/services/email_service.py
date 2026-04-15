"""
Gmail SMTP email service for sending pay stub PDFs.

Uses Gmail SMTP with App Passwords — no OAuth tokens, no expiry issues.

Required Railway env vars:
    GMAIL_USER_ACUMEN           — noreply.acumenpay@gmail.com
    GMAIL_APP_PASSWORD_ACUMEN   — Gmail App Password for acumen account
    GMAIL_USER_MAZ              — noreply.mazpay@gmail.com
    GMAIL_APP_PASSWORD_MAZ      — Gmail App Password for maz account
"""

import os
import re
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
from pathlib import Path

from backend.utils.test_mode import redirect_email, test_subject


# Map company name keywords → (user env var, app password env var)
COMPANY_ACCOUNTS = {
    "acumen":     ("GMAIL_USER_ACUMEN", "GMAIL_APP_PASSWORD_ACUMEN"),
    "maz":        ("GMAIL_USER_MAZ",    "GMAIL_APP_PASSWORD_MAZ"),
    "everdriven": ("GMAIL_USER_MAZ",    "GMAIL_APP_PASSWORD_MAZ"),
    "firstalt":   ("GMAIL_USER_ACUMEN", "GMAIL_APP_PASSWORD_ACUMEN"),
}


def _get_smtp_credentials(company: str) -> tuple[str, str]:
    """Return (from_email, app_password) for the given company."""
    key = company.lower().replace(" ", "").replace("international", "")
    user_var = "GMAIL_USER"
    pw_var   = "GMAIL_APP_PASSWORD"
    for prefix, (u, p) in COMPANY_ACCOUNTS.items():
        if prefix in key:
            user_var, pw_var = u, p
            break

    from_email   = os.environ.get(user_var, os.environ.get("GMAIL_USER", "")).strip()
    app_password = os.environ.get(pw_var,   os.environ.get("GMAIL_APP_PASSWORD", "")).strip()

    if not from_email or not app_password:
        missing = [k for k, v in {user_var: from_email, pw_var: app_password}.items() if not v]
        raise ValueError(f"Gmail credentials not configured. Missing: {', '.join(missing)}")

    return from_email, app_password


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

    from_email, app_password = _get_smtp_credentials(company)

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

    # Send via Gmail SMTP with App Password (no OAuth, no expiry)
    context = ssl.create_default_context()
    with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
        smtp.ehlo()
        smtp.starttls(context=context)
        smtp.login(from_email, app_password)
        smtp.send_message(msg)
