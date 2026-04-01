#!/usr/bin/env python3
"""
Auto-sync drivers from FirstAlt and EverDriven into the Person table.
Runs on startup via entrypoint.sh after migrations complete.
Safe to re-run — only adds/updates, never deletes.
"""
import os
import sys
import re

sys.path.insert(0, "/app")

from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+psycopg://app:secret@db:5432/appdb")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

def norm(name: str) -> str:
    return " ".join(name.lower().split()) if name else ""


def sync_firstalt(db):
    from backend.services import firstalt_service
    from backend.db.models import Person

    print("[sync_drivers] Syncing FirstAlt drivers...")
    try:
        drivers = firstalt_service.get_all_drivers()
    except Exception as e:
        print(f"[sync_drivers] FirstAlt fetch failed: {e}")
        return 0, 0

    matched = created = 0
    for drv in drivers:
        driver_id = drv.get("driverId")
        if not driver_id:
            continue

        first = (drv.get("firstName") or "").strip()
        mid   = (drv.get("middleName") or "").strip()
        last  = (drv.get("lastName") or "").strip()
        full  = " ".join(p for p in [first, mid, last] if p)
        if not full:
            continue

        # Skip if already linked
        existing = db.query(Person).filter(Person.firstalt_driver_id == driver_id).first()
        if existing:
            continue

        normed = norm(full)
        person = db.query(Person).filter(
            func.lower(func.regexp_replace(func.trim(Person.full_name), r'\s+', ' ', 'g')) == normed
        ).first()

        if person:
            if person.firstalt_driver_id is None:
                person.firstalt_driver_id = driver_id
                db.add(person)
                matched += 1
        else:
            person = Person(full_name=full, firstalt_driver_id=driver_id)
            db.add(person)
            created += 1

    db.commit()
    print(f"[sync_drivers] FirstAlt: {matched} matched, {created} created")
    return matched, created


def sync_everdriven(db):
    from backend.services import everdriven_service
    from backend.services.everdriven_service import EverDrivenAuthError
    from backend.db.models import Person

    print("[sync_drivers] Syncing EverDriven drivers...")
    try:
        drivers = everdriven_service.get_all_drivers()
    except EverDrivenAuthError:
        print("[sync_drivers] EverDriven auth required — skipping ED sync (login via /dispatch/everdriven/auth)")
        return 0, 0
    except Exception as e:
        print(f"[sync_drivers] EverDriven fetch failed: {e}")
        return 0, 0

    matched = created = 0
    for drv in drivers:
        driver_code = drv.get("keyValue") or drv.get("driverCode")
        driver_name = drv.get("name") or drv.get("driverName") or ""
        if not driver_code or not driver_name:
            continue

        try:
            driver_code_int = int(driver_code)
        except (ValueError, TypeError):
            continue

        existing = db.query(Person).filter(Person.everdriven_driver_id == driver_code_int).first()
        if existing:
            continue

        normed = norm(driver_name)
        person = db.query(Person).filter(
            func.lower(func.regexp_replace(func.trim(Person.full_name), r'\s+', ' ', 'g')) == normed
        ).first()

        if person:
            if person.everdriven_driver_id is None:
                person.everdriven_driver_id = driver_code_int
                db.add(person)
                matched += 1
        else:
            person = Person(full_name=driver_name, everdriven_driver_id=driver_code_int)
            db.add(person)
            created += 1

    db.commit()
    print(f"[sync_drivers] EverDriven: {matched} matched, {created} created")
    return matched, created


if __name__ == "__main__":
    db = SessionLocal()
    try:
        sync_firstalt(db)
        sync_everdriven(db)
        print("[sync_drivers] Driver sync complete.")
    finally:
        db.close()
