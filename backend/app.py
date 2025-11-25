# backend/app.py

"""
from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from backend.routes.people import router as people_router
from backend.routes.upload import router as upload_router
from backend.routes.summary import router as summary_router
from backend.routes.rides import router as rides_router

app = FastAPI(title="ZPay", version="0.1.0")

# mount routers (choose your style and keep it consistent)
#app.include_router(people_router, prefix="/people", tags=["people"])
#app.include_router(upload_router,  prefix="/upload", tags=["upload"])
#app.include_router(summary_router, prefix="/summary", tags=["summary"])
app.include_router(people_router)
app.include_router(upload_router)
app.include_router(summary_router)  # <-- add
app.include_router(rides_router)    # <-- add

@app.get("/", include_in_schema=False)
def root():
    # send root visitors to your people page (or "/docs")
    return RedirectResponse(url="/people")

@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"ok": True}
"""


from fastapi import FastAPI, Request, Depends, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates  # FastAPI wrapper around Starlette
from pathlib import Path

app = FastAPI(title="ZPay", version="0.1.0")

# Jinja templates
templates = Jinja2Templates(directory="backend/templates")
app.state.templates = templates  # so routers can access it

# Include your upload router (must exist)
from backend.routes import upload
app.include_router(upload.router)

# Root: render the page OR redirect to /upload
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    # Option A: redirect
    return RedirectResponse(url="/upload", status_code=303)
    # Option B: render directly (uncomment if you want a dedicated template)
    # return templates.TemplateResponse("upload.html", {"request": request})
