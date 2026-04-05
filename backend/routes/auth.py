"""Login / logout routes — multi-user."""

from pathlib import Path

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from backend.middleware.auth import authenticate, create_session, verify_session, COOKIE_NAME, MAX_AGE

router = APIRouter(tags=["auth"])

_templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "templates"))


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = ""):
    cookie = request.cookies.get(COOKIE_NAME)
    if cookie and verify_session(cookie):
        return RedirectResponse(url="/", status_code=302)
    return _templates.TemplateResponse(request, "login.html", {"error": error})


@router.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    user = authenticate(username, password)
    if user:
        response = RedirectResponse(url="/", status_code=302)
        token = create_session(
            username=user["username"],
            display_name=user["display_name"],
            color=user["color"],
            initials=user["initials"],
        )
        response.set_cookie(
            key=COOKIE_NAME,
            value=token,
            max_age=MAX_AGE,
            httponly=True,
            samesite="lax",
        )
        return response

    return _templates.TemplateResponse(
        request,
        "login.html",
        {"error": "Invalid username or password."},
        status_code=401,
    )


@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(COOKIE_NAME)
    return response
