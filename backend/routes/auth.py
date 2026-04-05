"""Login / logout routes."""

import os
from pathlib import Path

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from backend.middleware.auth import create_session, verify_session, COOKIE_NAME, MAX_AGE

router = APIRouter(tags=["auth"])

_templates_dir = Path(__file__).resolve().parents[1] / "templates"
_templates = Jinja2Templates(directory=str(_templates_dir))


def _check_password(pw: str) -> bool:
    correct = os.environ.get("ZPAY_PASSWORD", "zpay2026")
    return pw.strip() == correct


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = ""):
    # Already logged in? Redirect to dashboard
    cookie = request.cookies.get(COOKIE_NAME)
    if cookie and verify_session(cookie):
        return RedirectResponse(url="/", status_code=302)

    return _templates.TemplateResponse(request, "login.html", {
        "error": error,
    })


@router.post("/login")
async def login_submit(request: Request, password: str = Form(...)):
    if _check_password(password):
        response = RedirectResponse(url="/", status_code=302)
        response.set_cookie(
            key=COOKIE_NAME,
            value=create_session(),
            max_age=MAX_AGE,
            httponly=True,
            samesite="lax",
        )
        return response

    # Wrong password — re-render login with error
    return _templates.TemplateResponse(
        request,
        "login.html",
        {"error": "Invalid password. Try again."},
        status_code=401,
    )


@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(COOKIE_NAME)
    return response
