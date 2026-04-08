"""
Gmail SMTP email service for sending pay stub PDFs.

Requires in .env:
    GMAIL_USER=you@gmail.com
    GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
"""

import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
from pathlib import Path


COMPANY_ACCOUNTS = {
    "acumen": ("GMAIL_USER_ACUMEN", "GMAIL_APP_PASSWORD_ACUMEN"),
    "maz":    ("GMAIL_USER_MAZ",    "GMAIL_APP_PASSWORD_MAZ"),
    "everdriven": ("GMAIL_USER_MAZ", "GMAIL_APP_PASSWORD_MAZ"),
}

def _credentials(company: str = "") -> tuple[str, str]:
    key = company.lower().replace(" ", "").replace("international", "")
    for prefix, (user_key, pw_key) in COMPANY_ACCOUNTS.items():
        if prefix in key:
            user = os.environ.get(user_key, "").strip()
            pw   = os.environ.get(pw_key, "").strip()
            if user and pw:
                return user, pw

    # fallback to generic
    user = os.environ.get("GMAIL_USER", "").strip()
    pw   = os.environ.get("GMAIL_APP_PASSWORD", "").strip()
    if not user or not pw:
        raise ValueError("No Gmail credentials configured for company: " + company)
    return user, pw


def _body_to_html(body: str, company: str, subject: str) -> str:
    """
    Wrap the email body in a clean HTML template.
    If body is already HTML (starts with a tag), use it as-is.
    If it's plain text, convert newlines to <br>/<p> tags.
    """
    body = body.strip()

    if body.startswith("<"):
        # Already HTML from the rich-text editor
        content_html = body
    else:
        # Plain text — convert paragraphs and line breaks
        paragraphs = body.split("\n\n")
        content_html = "".join(
            f'<p style="margin:0 0 18px 0">{p.replace(chr(10), "<br>")}</p>'
            for p in paragraphs if p.strip()
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
</head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;">
  <div style="max-width:600px;margin:32px auto;background:#ffffff;border-radius:10px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08);">

    <!-- Header -->
    <div style="background:#0f172a;padding:28px 36px;">
      <div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.12em;color:#64748b;margin-bottom:6px;">Pay Stub</div>
      <div style="font-size:20px;font-weight:700;color:#f8fafc;letter-spacing:-0.3px;">{subject}</div>
      <div style="font-size:13px;color:#94a3b8;margin-top:4px;">{company}</div>
    </div>

    <!-- Body -->
    <div style="padding:36px;font-size:15px;color:#374151;line-height:1.8;">
      {content_html}
    </div>

    <!-- Divider -->
    <div style="height:1px;background:#e2e8f0;margin:0 36px;"></div>

    <!-- Footer -->
    <div style="padding:20px 36px;font-size:12px;color:#94a3b8;line-height:1.6;">
      Your pay stub PDF is attached to this email.<br>
      Questions? Reply to this email or contact your coordinator.
    </div>

  </div>
</body>
</html>"""


def _html_to_plain(html: str) -> str:
    """Strip HTML tags for plain-text fallback (for email clients that don't render HTML)."""
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
    """Send a single pay stub PDF to a driver, using DB email template if available."""
    gmail_user, gmail_pw = _credentials(company)

    # Resolve subject + body from template
    if db is not None:
        from backend.routes.email_templates import get_template, render_template
        tmpl = get_template(db, person_id=person_id, batch_id=payroll_batch_id)
        ctx = {
            "driver_name": driver_name,
            "first_name": (driver_name.split() or ["Driver"])[0],
            "week_start": week_start or payweek,
            "week_end": week_end or payweek,
            "total_pay": total_pay,
            "ride_count": str(ride_count),
            "company_name": company,
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

    # Build HTML + plain-text versions
    html_email = _body_to_html(body, company=company, subject=subject)
    plain_email = _html_to_plain(html_email)

    # Assemble multipart/alternative message (HTML preferred, plain fallback)
    msg = MIMEMultipart("mixed")
    msg["From"] = gmail_user
    msg["To"] = to_email
    msg["Subject"] = subject

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(plain_email, "plain", "utf-8"))
    alt.attach(MIMEText(html_email, "html", "utf-8"))
    msg.attach(alt)

    # Attach PDF
    with open(pdf_path, "rb") as f:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header(
        "Content-Disposition",
        f'attachment; filename="{pdf_path.name}"',
    )
    msg.attach(part)

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(gmail_user, gmail_pw)
        server.sendmail(gmail_user, to_email, msg.as_string())
