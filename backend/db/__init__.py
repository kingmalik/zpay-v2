# /app/backend/db/__init__.py
from .db import SessionLocal, engine, Base

# FastAPI-friendly dependency for sessions
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

__all__ = ["SessionLocal", "engine", "Base", "get_db"]
