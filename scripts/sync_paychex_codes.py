"""
One-time script: match Z-Pay drivers to Paychex Worker IDs by name.
Reads data/paychex_workers.csv and updates Person.paycheck_code in the DB.

Usage:
    python scripts/sync_paychex_codes.py          # dry-run (show matches)
    python scripts/sync_paychex_codes.py --apply   # actually update DB
"""

import csv
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.db import SessionLocal
from backend.db.models import Person


def normalize(name: str) -> str:
    """Normalize a name for fuzzy matching."""
    name = name.strip().lower()
    # Handle "Last, First" → "first last"
    if "," in name:
        parts = [p.strip() for p in name.split(",", 1)]
        name = f"{parts[1]} {parts[0]}"
    # Remove middle initials and suffixes
    name = name.replace(".", "").replace("  ", " ")
    return name


def load_paychex_workers():
    """Load Paychex workers from CSV."""
    csv_path = Path(__file__).resolve().parents[1] / "data" / "paychex_workers.csv"
    workers = {}
    with open(csv_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pid = row["paychex_id"].strip()
            name = row["name"].strip()
            workers[pid] = name
    return workers


def match_workers(apply: bool = False):
    paychex = load_paychex_workers()
    db = SessionLocal()

    try:
        persons = db.query(Person).filter(Person.active == True).all()

        # Build normalized lookup for Paychex names
        paychex_norm = {}
        for pid, name in paychex.items():
            paychex_norm[normalize(name)] = (pid, name)

        matched = []
        unmatched_zpay = []
        already_set = []

        for person in persons:
            zpay_name = person.full_name or ""
            zpay_norm = normalize(zpay_name)

            if person.paycheck_code:
                already_set.append((person.full_name, person.paycheck_code))
                continue

            # Try exact normalized match
            if zpay_norm in paychex_norm:
                pid, px_name = paychex_norm[zpay_norm]
                matched.append((person.person_id, person.full_name, pid, px_name))
                if apply:
                    person.paycheck_code = pid
                continue

            # Try partial match — first+last only
            zpay_parts = zpay_norm.split()
            found = False
            for norm_name, (pid, px_name) in paychex_norm.items():
                px_parts = norm_name.split()
                # Match if first and last name match (ignore middle)
                if len(zpay_parts) >= 2 and len(px_parts) >= 2:
                    if zpay_parts[0] == px_parts[0] and zpay_parts[-1] == px_parts[-1]:
                        matched.append((person.person_id, person.full_name, pid, px_name))
                        if apply:
                            person.paycheck_code = pid
                        found = True
                        break
                # Match single name
                elif len(zpay_parts) == 1 and len(px_parts) == 1:
                    if zpay_parts[0] == px_parts[0]:
                        matched.append((person.person_id, person.full_name, pid, px_name))
                        if apply:
                            person.paycheck_code = pid
                        found = True
                        break

            if not found:
                unmatched_zpay.append(person.full_name)

        if apply:
            db.commit()

        # Report
        print(f"\n{'=' * 60}")
        print(f"  Paychex Code Sync {'(DRY RUN)' if not apply else '(APPLIED)'}")
        print(f"{'=' * 60}")

        if already_set:
            print(f"\n  Already have codes ({len(already_set)}):")
            for name, code in sorted(already_set):
                print(f"    {name:<35} → {code}")

        if matched:
            print(f"\n  Matched ({len(matched)}):")
            for pid, zpay, px_id, px_name in sorted(matched, key=lambda x: x[1]):
                print(f"    {zpay:<35} → ID {px_id} ({px_name})")

        if unmatched_zpay:
            print(f"\n  ⚠ Unmatched Z-Pay drivers ({len(unmatched_zpay)}):")
            for name in sorted(unmatched_zpay):
                print(f"    {name}")

        print(f"\n  Summary: {len(matched)} matched, {len(already_set)} already set, {len(unmatched_zpay)} unmatched")

        if not apply and matched:
            print(f"\n  Run with --apply to update the database.")

    finally:
        db.close()


if __name__ == "__main__":
    apply = "--apply" in sys.argv
    match_workers(apply=apply)
