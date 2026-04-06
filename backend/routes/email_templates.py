"""
Email template management — default, per-batch, and per-person overrides.
"""
from pathlib import Path
from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Query
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.db.models import EmailTemplate, PayrollBatch, Person, Ride

router = APIRouter(prefix="/email/templates", tags=["email-templates"])

_DEFAULT_SUBJECT = "Your Pay Stub is Ready"
_DEFAULT_BODY = (
    "<p>Hi,</p>"
    "<p>Please find attached your pay stub for this pay period.</p>"
    "<p>If you have any questions, please reach out.</p>"
)

# Map readable tokens → context keys (used by render_template)
_TOKEN_MAP = {
    "[First Name]":  "first_name",
    "[Full Name]":   "driver_name",
    "[Week Start]":  "week_start",
    "[Week End]":    "week_end",
    "[Total Pay]":   "total_pay",
    "[Ride Count]":  "ride_count",
    "[Company]":     "company_name",
}


def _templates(request: Request) -> Jinja2Templates:
    t = getattr(request.app.state, "templates", None)
    if t:
        return t
    return Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "templates"))


def get_template(db: Session, person_id: int | None = None, batch_id: int | None = None) -> dict:
    """
    Look up the most specific template available.
    Priority: person-level → batch-level → default
    Returns a dict with subject and body (falling back to built-in defaults).
    """
    # person-level
    if person_id:
        t = db.query(EmailTemplate).filter(
            EmailTemplate.scope == "person",
            EmailTemplate.person_id == person_id,
        ).first()
        if t:
            return {"subject": t.subject, "body": t.body}

    # batch-level
    if batch_id:
        t = db.query(EmailTemplate).filter(
            EmailTemplate.scope == "batch",
            EmailTemplate.payroll_batch_id == batch_id,
        ).first()
        if t:
            return {"subject": t.subject, "body": t.body}

    # default
    t = db.query(EmailTemplate).filter(EmailTemplate.scope == "default").first()
    if t:
        return {"subject": t.subject, "body": t.body}

    return {"subject": _DEFAULT_SUBJECT, "body": _DEFAULT_BODY}


def render_template(tmpl: dict, context: dict) -> tuple[str, str]:
    """Substitute [Readable Token] and legacy {{placeholder}} tokens in subject and body."""
    subject = tmpl["subject"]
    body = tmpl["body"]
    # New readable-token syntax: [First Name], [Company], etc.
    for readable, key in _TOKEN_MAP.items():
        value = str(context.get(key, ""))
        subject = subject.replace(readable, value)
        body = body.replace(readable, value)
    # Legacy {{key}} syntax — kept for backwards compat with saved templates
    for key, value in context.items():
        token = "{{" + key + "}}"
        subject = subject.replace(token, str(value))
        body = body.replace(token, str(value))
    return subject, body


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("", name="email_templates_page")
def templates_page(
    request: Request,
    db: Session = Depends(get_db),
    edit_batch: int | None = Query(None),
    edit_person: int | None = Query(None),
):
    default_tmpl = db.query(EmailTemplate).filter(EmailTemplate.scope == "default").first()

    batch_overrides = (
        db.query(EmailTemplate, PayrollBatch)
        .join(PayrollBatch, PayrollBatch.payroll_batch_id == EmailTemplate.payroll_batch_id)
        .filter(EmailTemplate.scope == "batch")
        .order_by(PayrollBatch.week_start.desc())
        .all()
    )

    person_overrides = (
        db.query(EmailTemplate, Person)
        .join(Person, Person.person_id == EmailTemplate.person_id)
        .filter(EmailTemplate.scope == "person")
        .order_by(Person.full_name)
        .all()
    )

    # For dropdowns
    recent_batches = (
        db.query(PayrollBatch)
        .order_by(PayrollBatch.week_start.desc())
        .limit(30)
        .all()
    )
    active_drivers = (
        db.query(Person)
        .filter(Person.active == True)
        .order_by(Person.full_name)
        .all()
    )

    # Build preview context — use real data if editing a specific batch or person
    sample_context = {
        "driver_name": "Jane Smith",
        "first_name": "Jane",
        "week_start": "3/17/2026",
        "week_end": "3/21/2026",
        "total_pay": "423.50",
        "ride_count": "9",
        "company_name": "Z-Pay",
    }

    focused_batch = None
    focused_person = None
    batch_pay_preview = None
    person_pay_preview = None

    if edit_batch:
        focused_batch = db.get(PayrollBatch, edit_batch)
        if focused_batch:
            # Pull real stats for this batch to drive preview
            stats = (
                db.query(
                    func.count(Ride.ride_id).label("ride_count"),
                    func.sum(Ride.z_rate).label("total_pay"),
                )
                .filter(Ride.payroll_batch_id == edit_batch)
                .one()
            )
            ws = focused_batch.week_start
            we = focused_batch.week_end
            sample_context = {
                "driver_name": "Your Driver",
                "first_name": "Driver",
                "week_start": ws.strftime("%-m/%-d/%Y") if ws else "—",
                "week_end": we.strftime("%-m/%-d/%Y") if we else "—",
                "total_pay": f"{float(stats.total_pay or 0) / max(1, int(stats.ride_count or 1)):.2f}",
                "ride_count": str(int(stats.ride_count or 0)),
                "company_name": focused_batch.company_name or "Z-Pay",
            }
            batch_pay_preview = {
                "week": f"{ws.strftime('%-m/%-d') if ws else '?'} – {we.strftime('%-m/%-d/%Y') if we else '?'}",
                "company": focused_batch.company_name,
                "total_drivers": db.query(func.count(Ride.person_id.distinct())).filter(Ride.payroll_batch_id == edit_batch).scalar() or 0,
                "total_pay": round(float(stats.total_pay or 0), 2),
                "total_rides": int(stats.ride_count or 0),
            }

    if edit_person:
        focused_person = db.get(Person, edit_person)
        if focused_person:
            # Pull their most recent batch data
            last = (
                db.query(
                    PayrollBatch.week_start,
                    PayrollBatch.week_end,
                    PayrollBatch.company_name,
                    func.count(Ride.ride_id).label("ride_count"),
                    func.sum(Ride.z_rate).label("total_pay"),
                )
                .join(Ride, Ride.payroll_batch_id == PayrollBatch.payroll_batch_id)
                .filter(Ride.person_id == edit_person)
                .group_by(PayrollBatch.payroll_batch_id, PayrollBatch.week_start, PayrollBatch.week_end, PayrollBatch.company_name)
                .order_by(PayrollBatch.week_start.desc())
                .first()
            )
            if last:
                ws, we = last.week_start, last.week_end
                first_name = focused_person.full_name.split()[0] if focused_person.full_name else "Driver"
                sample_context = {
                    "driver_name": focused_person.full_name,
                    "first_name": first_name,
                    "week_start": ws.strftime("%-m/%-d/%Y") if ws else "—",
                    "week_end": we.strftime("%-m/%-d/%Y") if we else "—",
                    "total_pay": f"{float(last.total_pay or 0):.2f}",
                    "ride_count": str(int(last.ride_count or 0)),
                    "company_name": last.company_name or "Z-Pay",
                }
                person_pay_preview = {
                    "name": focused_person.full_name,
                    "last_week": f"{ws.strftime('%-m/%-d') if ws else '?'} – {we.strftime('%-m/%-d/%Y') if we else '?'}",
                    "total_pay": round(float(last.total_pay or 0), 2),
                    "ride_count": int(last.ride_count or 0),
                    "company": last.company_name,
                }

    # Fetch existing override templates so the edit forms can pre-populate
    edit_batch_tmpl = None
    if edit_batch:
        edit_batch_tmpl = db.query(EmailTemplate).filter(
            EmailTemplate.scope == "batch",
            EmailTemplate.payroll_batch_id == edit_batch,
        ).first()

    edit_person_tmpl = None
    if edit_person:
        edit_person_tmpl = db.query(EmailTemplate).filter(
            EmailTemplate.scope == "person",
            EmailTemplate.person_id == edit_person,
        ).first()

    # Preview default template
    preview_subj, preview_body = render_template(
        {"subject": default_tmpl.subject if default_tmpl else _DEFAULT_SUBJECT,
         "body": default_tmpl.body if default_tmpl else _DEFAULT_BODY},
        sample_context,
    )

    return _templates(request).TemplateResponse(
        request,
        "email_templates.html",
        {
            "default_tmpl": default_tmpl,
            "default_subject": _DEFAULT_SUBJECT,
            "default_body": _DEFAULT_BODY,
            "batch_overrides": batch_overrides,
            "person_overrides": person_overrides,
            "recent_batches": recent_batches,
            "active_drivers": active_drivers,
            "preview_subject": preview_subj,
            "preview_body": preview_body,
            "sample_context": sample_context,
            # Focused edit context
            "edit_batch": edit_batch,
            "edit_person": edit_person,
            "focused_batch": focused_batch,
            "focused_person": focused_person,
            "batch_pay_preview": batch_pay_preview,
            "person_pay_preview": person_pay_preview,
            # Existing templates to pre-fill override forms
            "edit_batch_tmpl": edit_batch_tmpl,
            "edit_person_tmpl": edit_person_tmpl,
        },
    )


@router.post("/save-default", name="save_default_template")
def save_default(
    subject: str = Form(...),
    body: str = Form(...),
    db: Session = Depends(get_db),
):
    tmpl = db.query(EmailTemplate).filter(EmailTemplate.scope == "default").first()
    if tmpl:
        tmpl.subject = subject
        tmpl.body = body
    else:
        tmpl = EmailTemplate(scope="default", subject=subject, body=body)
        db.add(tmpl)
    db.commit()
    return RedirectResponse(url="/email/templates", status_code=303)


@router.post("/save-batch", name="save_batch_template")
def save_batch(
    payroll_batch_id: int = Form(...),
    subject: str = Form(""),
    body: str = Form(""),
    db: Session = Depends(get_db),
):
    # Allow blank subject/body — treat as "remove override" if both are blank
    if not subject.strip() and not body.strip():
        # Delete any existing override rather than saving an empty one
        existing = db.query(EmailTemplate).filter(
            EmailTemplate.scope == "batch",
            EmailTemplate.payroll_batch_id == payroll_batch_id,
        ).first()
        if existing:
            db.delete(existing)
            db.commit()
        return RedirectResponse(url="/email/templates", status_code=303)

    tmpl = db.query(EmailTemplate).filter(
        EmailTemplate.scope == "batch",
        EmailTemplate.payroll_batch_id == payroll_batch_id,
    ).first()
    if tmpl:
        tmpl.subject = subject
        tmpl.body = body
    else:
        tmpl = EmailTemplate(scope="batch", payroll_batch_id=payroll_batch_id, subject=subject, body=body)
        db.add(tmpl)
    db.commit()
    return RedirectResponse(url="/email/templates", status_code=303)


@router.post("/save-person", name="save_person_template")
def save_person(
    person_id: int = Form(...),
    subject: str = Form(""),
    body: str = Form(""),
    db: Session = Depends(get_db),
):
    # Allow blank subject/body — treat as "remove override" if both are blank
    if not subject.strip() and not body.strip():
        existing = db.query(EmailTemplate).filter(
            EmailTemplate.scope == "person",
            EmailTemplate.person_id == person_id,
        ).first()
        if existing:
            db.delete(existing)
            db.commit()
        return RedirectResponse(url="/email/templates", status_code=303)

    tmpl = db.query(EmailTemplate).filter(
        EmailTemplate.scope == "person",
        EmailTemplate.person_id == person_id,
    ).first()
    if tmpl:
        tmpl.subject = subject
        tmpl.body = body
    else:
        tmpl = EmailTemplate(scope="person", person_id=person_id, subject=subject, body=body)
        db.add(tmpl)
    db.commit()
    return RedirectResponse(url="/email/templates", status_code=303)


@router.post("/delete/{template_id}", name="delete_template")
def delete_template(template_id: int, db: Session = Depends(get_db)):
    tmpl = db.get(EmailTemplate, template_id)
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")
    if tmpl.scope == "default":
        raise HTTPException(status_code=400, detail="Cannot delete the default template — reset it instead")
    db.delete(tmpl)
    db.commit()
    return RedirectResponse(url="/email/templates", status_code=303)
