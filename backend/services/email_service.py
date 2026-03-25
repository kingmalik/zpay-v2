"""
Gmail SMTP email service for sending pay stub PDFs.

Requires in .env:
    GMAIL_USER=you@gmail.com
    GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
"""

import os
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
    # match acumen or maz/everdriven
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


def send_paystub(
    to_email: str,
    driver_name: str,
    company: str,
    payweek: str,
    pdf_path: Path,
) -> None:
    """Send a single pay stub PDF to a driver."""
    gmail_user, gmail_pw = _credentials(company)

    msg = MIMEMultipart()
    msg["From"] = gmail_user
    msg["To"] = to_email
    msg["Subject"] = f"{company} — Pay Stub: {payweek}"

    body = (
        f"Hi {driver_name.split()[0]},\n\n"
        f"Please find attached your pay stub for the pay period: {payweek}.\n\n"
        f"If you have any questions, please reach out.\n\n"
        f"— {company}"
    )
    msg.attach(MIMEText(body, "plain"))

    with open(pdf_path, "rb") as f:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header(
        "Content-Disposition",
        f'attachment; filename="{pdf_path.name}"',
    )
    msg.attach(part)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_user, gmail_pw)
        server.sendmail(gmail_user, to_email, msg.as_string())
