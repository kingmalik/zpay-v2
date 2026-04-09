"""
reconcile_paycheck_codes.py
----------------------------
Matches paychex_workers.csv → Person table and updates paycheck_code.

Usage:
    # Dry run (default — prints what WOULD change, no writes):
    python scripts/reconcile_paycheck_codes.py

    # Actually write to DB:
    python scripts/reconcile_paycheck_codes.py --apply

Environment:
    DATABASE_URL — SQLAlchemy-compatible PostgreSQL connection string.
"""

import argparse
import csv
import difflib
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# Path gymnastics so the script can be run from the repo root
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.db.models import Person  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
CSV_PATH = ROOT / "data" / "paychex_workers.csv"
FUZZY_THRESHOLD = 0.82


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def normalize_csv_name(raw: str) -> str:
    """
    Convert "Last, First" or "Last, First Middle" → "First Last"
    (or "First Middle Last" when a middle name is present).
    Lowercased and stripped.
    """
    raw = raw.strip()
    if "," in raw:
        parts = raw.split(",", 1)
        last = parts[0].strip()
        rest = parts[1].strip()          # "First" or "First Middle"
        canonical = f"{rest} {last}"
    else:
        canonical = raw
    return canonical.lower().strip()


def normalize_db_name(full_name: str) -> str:
    """Lower-case, stripped — already "First Last" in the DB."""
    return full_name.lower().strip()


def best_match(
    csv_norm: str,
    db_persons: list[Person],
    db_norms: list[str],
) -> tuple[Person | None, float]:
    """Return (Person, ratio) for the best DB match, or (None, 0) if below threshold."""
    best_person: Person | None = None
    best_ratio = 0.0

    for person, db_norm in zip(db_persons, db_norms):
        if csv_norm == db_norm:
            return person, 1.0  # exact — short-circuit
        ratio = difflib.SequenceMatcher(None, csv_norm, db_norm).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_person = person

    if best_ratio >= FUZZY_THRESHOLD:
        return best_person, best_ratio
    return None, best_ratio


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Reconcile Paychex codes into Person table.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=True,
        help="Print planned changes without writing (default).",
    )
    mode.add_argument(
        "--apply",
        dest="dry_run",
        action="store_false",
        help="Write updates to the database.",
    )
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        sys.exit("ERROR: DATABASE_URL environment variable is not set.")

    if not CSV_PATH.exists():
        sys.exit(f"ERROR: CSV file not found at {CSV_PATH}")

    # -----------------------------------------------------------------------
    # Load CSV
    # -----------------------------------------------------------------------
    csv_rows: list[dict] = []
    with open(CSV_PATH, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            csv_rows.append(
                {
                    "paychex_id": row["paychex_id"].strip(),
                    "raw_name": row["name"].strip(),
                    "norm_name": normalize_csv_name(row["name"]),
                }
            )

    print(f"\n{'='*60}")
    print(f"  Paychex CSV loaded — {len(csv_rows)} entries")
    print(f"{'='*60}\n")

    # -----------------------------------------------------------------------
    # Load DB persons
    # -----------------------------------------------------------------------
    engine = create_engine(database_url)
    with Session(engine) as session:
        db_persons: list[Person] = session.query(Person).all()
        db_norms = [normalize_db_name(p.full_name) for p in db_persons]

        print(f"DB persons loaded — {len(db_persons)} total\n")

        # -----------------------------------------------------------------------
        # Match
        # -----------------------------------------------------------------------
        matched: list[tuple[dict, Person, float]] = []      # (csv_row, person, ratio)
        unmatched_csv: list[dict] = []

        for row in csv_rows:
            person, ratio = best_match(row["norm_name"], db_persons, db_norms)
            if person is not None:
                matched.append((row, person, ratio))
            else:
                unmatched_csv.append(row)

        # -----------------------------------------------------------------------
        # Report: matches
        # -----------------------------------------------------------------------
        print(f"{'─'*60}")
        print(f"  MATCHES FOUND ({len(matched)})")
        print(f"{'─'*60}")
        updates_needed = 0
        for row, person, ratio in matched:
            match_type = "exact" if ratio == 1.0 else f"fuzzy ({ratio:.2f})"
            will_change = person.paycheck_code != row["paychex_id"]
            change_flag = " [WILL UPDATE]" if will_change else " [no change]"
            if will_change:
                updates_needed += 1
            print(
                f"  CSV  : {row['raw_name']!r}  (paychex_id={row['paychex_id']})\n"
                f"  DB   : {person.full_name!r}  (person_id={person.person_id}, "
                f"current paycheck_code={person.paycheck_code!r})\n"
                f"  Match: {match_type}{change_flag}\n"
            )

        # -----------------------------------------------------------------------
        # Report: CSV entries with no DB match
        # -----------------------------------------------------------------------
        print(f"{'─'*60}")
        print(f"  CSV ENTRIES WITH NO DB MATCH ({len(unmatched_csv)})")
        print(f"{'─'*60}")
        if unmatched_csv:
            for row in unmatched_csv:
                print(f"  ✗  {row['raw_name']!r}  (paychex_id={row['paychex_id']})")
        else:
            print("  (none)")
        print()

        # -----------------------------------------------------------------------
        # Report: DB persons with no paycheck_code
        # -----------------------------------------------------------------------
        no_code = [p for p in db_persons if not p.paycheck_code]
        print(f"{'─'*60}")
        print(f"  DB PERSONS WITH NO PAYCHECK_CODE ({len(no_code)})")
        print(f"{'─'*60}")
        if no_code:
            for p in no_code:
                in_matched = any(person.person_id == p.person_id for _, person, _ in matched)
                will_get = " [will be set by this run]" if in_matched else ""
                print(f"  person_id={p.person_id}  name={p.full_name!r}{will_get}")
        else:
            print("  (none)")
        print()

        # -----------------------------------------------------------------------
        # Summary
        # -----------------------------------------------------------------------
        print(f"{'─'*60}")
        print(f"  SUMMARY")
        print(f"{'─'*60}")
        print(f"  CSV entries       : {len(csv_rows)}")
        print(f"  DB matched        : {len(matched)}")
        print(f"  CSV unmatched     : {len(unmatched_csv)}")
        print(f"  Updates needed    : {updates_needed}")
        print(f"  Mode              : {'DRY RUN — no changes written' if args.dry_run else 'APPLY'}")
        print()

        # -----------------------------------------------------------------------
        # Apply
        # -----------------------------------------------------------------------
        if args.dry_run:
            print("  Dry-run complete. Re-run with --apply to write changes.\n")
            return

        applied = 0
        for row, person, _ratio in matched:
            if person.paycheck_code != row["paychex_id"]:
                person.paycheck_code = row["paychex_id"]
                applied += 1

        session.commit()
        print(f"  Applied {applied} update(s) to the database.\n")


if __name__ == "__main__":
    main()
