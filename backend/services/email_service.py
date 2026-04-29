"""
Resend HTTP API email service for sending pay stub PDFs.

Uses Resend (https://resend.com) — works on Railway, no SMTP required, no
OAuth refresh tokens that expire weekly.

Required Railway env vars:
    RESEND_API_KEY        — single API key for all sends
    RESEND_FROM_ACUMEN    — e.g. "Acumen International <payroll@yourdomain.com>"
    RESEND_FROM_MAZ       — e.g. "Maz Services <payroll@yourdomain.com>"

The from-address must be on a Resend-verified domain.
"""

import os
import re
import base64
import json
import urllib.request
import urllib.error
from pathlib import Path

from backend.utils.test_mode import redirect_email, test_subject


# Map company name keywords → from-address env var.
# FirstAlt sends from the Acumen address; EverDriven sends from the Maz address —
# same as the prior Gmail setup.
COMPANY_FROM_ENV = {
    "acumen":     "RESEND_FROM_ACUMEN",
    "firstalt":   "RESEND_FROM_ACUMEN",
    "maz":        "RESEND_FROM_MAZ",
    "everdriven": "RESEND_FROM_MAZ",
}


def _get_from_email(company: str) -> str:
    """Resolve the from-address for the given company name."""
    key = company.lower().replace(" ", "").replace("international", "")
    from_env = "RESEND_FROM_ACUMEN"  # safe default
    for prefix, env_var in COMPANY_FROM_ENV.items():
        if prefix in key:
            from_env = env_var
            break

    from_email = os.environ.get(from_env, "").strip()
    if not from_email:
        raise ValueError(
            f"Resend from-address not configured. Missing env var: {from_env}"
        )
    return from_email


def _resend_send(*, from_email: str, to_email: str, subject: str,
                 html: str, text: str | None = None,
                 attachment_path: Path | None = None) -> None:
    """POST a single email to Resend's /emails endpoint.

    Optional ``attachment_path`` attaches one file (used by paystub PDFs).
    """
    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    if not api_key:
        raise ValueError("RESEND_API_KEY env var is not set.")

    payload: dict = {
        "from": from_email,
        "to": [to_email],
        "subject": subject,
        "html": html,
    }
    if text:
        payload["text"] = text

    if attachment_path is not None:
        with open(attachment_path, "rb") as f:
            attachment_b64 = base64.b64encode(f.read()).decode("ascii")
        payload["attachments"] = [{
            "filename": attachment_path.name,
            "content": attachment_b64,
        }]

    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Resend HTTP {exc.code}: {body}") from exc


def send_email(*, to_email: str, subject: str, html: str,
               text: str | None = None, company: str = "maz",
               attachment_bytes: bytes | None = None,
               attachment_filename: str | None = None) -> None:
    """Generic Resend send for non-paystub emails (alerts, onboarding, etc).

    Picks the from-address by company keyword the same way send_paystub does.
    Optional ``attachment_bytes`` + ``attachment_filename`` attaches one file.
    """
    to_email = redirect_email(to_email)
    subject = test_subject(subject)
    from_email = _get_from_email(company)

    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    if not api_key:
        raise ValueError("RESEND_API_KEY env var is not set.")

    payload: dict = {
        "from": from_email,
        "to": [to_email],
        "subject": subject,
        "html": html,
    }
    if text:
        payload["text"] = text
    if attachment_bytes is not None and attachment_filename:
        payload["attachments"] = [{
            "filename": attachment_filename,
            "content": base64.b64encode(attachment_bytes).decode("ascii"),
        }]

    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Resend HTTP {exc.code}: {body}") from exc


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
    """Send a pay stub PDF via Resend HTTP API."""
    # TEST MODE: redirect recipient email before any sending logic
    to_email = redirect_email(to_email)

    from_email = _get_from_email(company)

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

    _resend_send(
        from_email=from_email,
        to_email=to_email,
        subject=subject,
        html=html_email,
        text=plain_email,
        attachment_path=pdf_path,
    )
