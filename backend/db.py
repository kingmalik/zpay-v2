from __future__ import annotations
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://app:secret@db:5432/appdb")

# Engine & session factory
engine = create_engine(DATABASE_URL, future=True, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

# Optional: a safe helper you can call at startup to create tables
# if you don't have migrations set up yet. It's a no-op if tables already exist.
def ensure_schema():
    try:
        from backend.models import Base  # local import to avoid circulars
        Base.metadata.create_all(bind=engine)
    except Exception as e:
        # If you are using Alembic, you can ignore this or remove it.
        # It's here so a bare app with only models can still start.
        print(f"[ensure_schema] skipped or failed: {e}")
