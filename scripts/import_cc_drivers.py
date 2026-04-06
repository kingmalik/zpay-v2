"""
Import Contractor Compliance drivers from cc_drivers.csv into the Person table.

CSV fields: id, email, first_name, last_name, phone, avatar, companies, status, archived, compliance

Logic:
  - Skip archived drivers (archived != "")
  - Fuzzy-match "First Last" -> Person.full_name (threshold 80%)
  - If matched: update external_id (CC UUID), email, phone — only if currently NULL
  - If unmatched: INSERT new Person record
  - active = True if status == "Active", else False

Usage (Railway):
  railway run python scripts/import_cc_drivers.py [--dry-run] [--csv path/to/cc_drivers.csv]
"""

import csv
import os
import re
import sys
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

# ── Config ────────────────────────────────────────────────────────────────────
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    os.environ.get("DATABASE_PUBLIC_URL", "postgresql+psycopg://app:secret@db:5432/appdb"),
)
DEFAULT_CSV = Path(__file__).parent.parent / "data" / "cc_drivers.csv"
DRY_RUN = "--dry-run" in sys.argv

# ── Name helpers ──────────────────────────────────────────────────────────────
def _norm(name: str) -> str:
    if not name:
        return ""
    name = str(name).strip()
    name = re.sub(r"\s*-\s*Sub#?\d+.*$", "", name, flags=re.IGNORECASE)
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return " ".join(name.lower().split())


def _sim(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def best_match(name: str, persons: list[dict], threshold=0.80):
    best, best_score = None, 0.0
    for p in persons:
        score = _sim(name, p["full_name"])
        if score > best_score:
            best_score, best = score, p
    return (best, best_score) if best_score >= threshold else (None, best_score)


# ── CSV reader ────────────────────────────────────────────────────────────────
def load_csv(path: Path) -> list[dict]:
    drivers = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            # Skip archived
            if row.get("archived", "").strip():
                continue
            phone = re.sub(r"\D", "", row.get("phone", "") or "")
            drivers.append({
                "cc_id":      row["id"].strip(),
                "first_name": row.get("first_name", "").strip(),
                "last_name":  row.get("last_name", "").strip(),
                "full_name":  f"{row.get('first_name','').strip()} {row.get('last_name','').strip()}".strip(),
                "email":      row.get("email", "").strip() or None,
                "phone":      phone or None,
                "active":     row.get("status", "").strip().lower() == "active",
            })
    return drivers


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    # CSV path
    csv_arg = next((sys.argv[i + 1] for i, a in enumerate(sys.argv) if a == "--csv"), None)
    csv_path = Path(csv_arg) if csv_arg else DEFAULT_CSV
    if not csv_path.exists():
        print(f"ERROR: CSV not found: {csv_path}")
        sys.exit(1)

    drivers = load_csv(csv_path)
    print(f"Loaded {len(drivers)} active CC drivers from {csv_path.name}")

    engine = create_engine(DATABASE_URL, future=True)

    with Session(engine) as session:
        persons = [
            dict(r._mapping)
            for r in session.execute(
                text("SELECT person_id, full_name, external_id, email, phone FROM person ORDER BY person_id")
            ).fetchall()
        ]
        print(f"Found {len(persons)} existing persons in DB\n")

        updated = 0
        inserted = 0
        skipped = 0
        unmatched = []

        for d in drivers:
            person, score = best_match(d["full_name"], persons)

            if person:
                updates = {}
                if d["cc_id"] and not person["external_id"]:
                    updates["external_id"] = d["cc_id"]
                if d["email"] and not person["email"]:
                    updates["email"] = d["email"]
                if d["phone"] and not person["phone"]:
                    updates["phone"] = d["phone"]

                if not updates:
                    print(f"  SKIP    ({score:.0%}) {person['full_name']} — already has all data")
                    skipped += 1
                    continue

                fields = ", ".join(updates.keys())
                print(f"  UPDATE  ({score:.0%}) {person['full_name']} ← {d['full_name']} [{fields}]")
                if not DRY_RUN:
                    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
                    updates["pid"] = person["person_id"]
                    session.execute(
                        text(f"UPDATE person SET {set_clause} WHERE person_id = :pid"),
                        updates,
                    )
                updated += 1

            else:
                print(f"  INSERT  (no match {score:.0%}) {d['full_name']} — adding as new person")
                unmatched.append(d["full_name"])
                if not DRY_RUN:
                    session.execute(
                        text(
                            "INSERT INTO person (external_id, full_name, email, phone, active) "
                            "VALUES (:external_id, :full_name, :email, :phone, :active)"
                        ),
                        {
                            "external_id": d["cc_id"],
                            "full_name":   d["full_name"],
                            "email":       d["email"],
                            "phone":       d["phone"],
                            "active":      d["active"],
                        },
                    )
                inserted += 1

        if not DRY_RUN:
            session.commit()

    print()
    if DRY_RUN:
        print("*** DRY RUN — no changes written ***")
    print(f"Summary: {updated} updated, {inserted} inserted, {skipped} skipped")
    if unmatched:
        print(f"\nNew persons inserted ({len(unmatched)}):")
        for name in unmatched:
            print(f"  + {name}")


if __name__ == "__main__":
    main()
