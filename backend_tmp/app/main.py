from fastapi import FastAPI
from .routers.upload import router as upload_router

app = FastAPI(title="ZPay Upload API", version="0.2.0")

app.include_router(upload_router, tags=["upload"])

@app.get("/healthz")
def healthz():
    return {"ok": True}
