"""
Duplicate Person Audit Script
==============================
READ-ONLY. Never modifies any data.

Finds candidate duplicate rows in the `person` table using three heuristics:
  1. Shared paycheck_code (Acumen) across 2+ person rows
  2. Shared paycheck_code_maz (Maz) across 2+ person rows
  3. Similar full_name (Levenshtein distance < 3 on lowercased trimmed names)

KNOWN FAMILY POOLING — explicitly excluded from duplicate detection:
  - person_id=45  (Elham Mohammedtahir)     ┐ share paycheck_code 1013 legitimately
  - person_id=291 (Mohammedtahir M seid Hussen) ┘  — this is a family account
  Add more known-pool pairs to FAMILY_POOL_PERSON_IDS below if needed.

Usage
-----
  cd /path/to/zpay-v2-fresh
  DATABASE_URL="postgresql://..." python -m backend.scripts.audit_duplicate_people
  DATABASE_URL="..." python -m backend.scripts.audit_duplicate_people --csv
  DATABASE_URL="..." python -m backend.scripts.audit_duplicate_people --apply

  --apply   Does NOTHING (safety flag). Prints a reminder that merging is a
            separate PR requiring Malik review.
  --csv     Outputs candidate clusters as CSV to stdout for spreadsheet review.
"""

from __future__ import annotations

import csv
import io
import sys
import argparse
import logging
from itertools import combinations
from pathlib import Path
from typing import Optional

# Ensure repo root is on sys.path when run as a module
_repo_root = Path(__file__).resolve().parents[2]
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
_logger = logging.getLogger("zpay.audit_duplicate_people")

# ── Known family-pooling pairs — SKIP from duplicate flagging ─────────────────
# These people legitimately share a Paychex code because they pool to one bank.
# Format: frozenset of person_ids that are known-family and NOT duplicates.
FAMILY_POOL_PERSON_IDS: frozenset[int] = frozenset({45, 291})
# paycheck_code 1013: Elham Mohammedtahir (45) + Mohammedtahir M seid Hussen (291)


def _levenshtein(a: str, b: str) -> int:
    """Simple iterative Levenshtein distance."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            curr.append(min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + (0 if ca == cb else 1)))
        prev = curr
    return prev[-1]


def _normalise(name: str) -> str:
    return name.strip().lower()


def main(args: argparse.Namespace) -> None:
    if args.apply:
        _logger.warning(
            "--apply was passed but this script NEVER modifies data. "
            "Row merges require a separate reviewed PR. "
            "Review the audit output below, then open a PR."
        )

    from backend.db import SessionLocal
    from backend.db.models import Person, Ride
    from sqlalchemy import func

    db = SessionLocal()
    try:
        persons = db.query(Person).order_by(Person.person_id.asc()).all()
        _logger.info("Loaded %d person rows", len(persons))

        # ── Ride counts per person_id ─────────────────────────────────────────
        ride_counts: dict[int, int] = {
            r.person_id: r.cnt
            for r in db.query(Ride.person_id, func.count(Ride.ride_id).label("cnt"))
            .group_by(Ride.person_id)
            .all()
        }

        # ── Build lookup structures ───────────────────────────────────────────
        # paycheck_code -> list of persons
        code_map: dict[str, list[Person]] = {}
        for p in persons:
            if p.paycheck_code:
                code_map.setdefault(p.paycheck_code, []).append(p)

        # paycheck_code_maz -> list of persons
        maz_map: dict[str, list[Person]] = {}
        for p in persons:
            if p.paycheck_code_maz:
                maz_map.setdefault(p.paycheck_code_maz, []).append(p)

        # ── Candidate clusters ─────────────────────────────────────────────────
        # Each cluster is a dict: reason + list of person rows
        Cluster = dict  # type alias for readability
        clusters: list[Cluster] = []
        seen_sets: list[frozenset[int]] = []

        def _is_family_pool(ids: frozenset[int]) -> bool:
            """Return True if ALL ids in this cluster are known family-pool members."""
            return ids.issubset(FAMILY_POOL_PERSON_IDS)

        def _add_cluster(reason: str, persons_in: list[Person]) -> None:
            ids = frozenset(p.person_id for p in persons_in)
            if _is_family_pool(ids):
                _logger.debug("Skipping family-pool cluster %s (%s)", ids, reason)
                return
            # Deduplicate: if we already have a superset cluster, skip
            for existing in seen_sets:
                if ids.issubset(existing):
                    return
            seen_sets.append(ids)
            clusters.append({"reason": reason, "persons": persons_in})

        # Heuristic 1: shared paycheck_code (Acumen)
        for code, ps in code_map.items():
            if len(ps) >= 2:
                _add_cluster(f"shared paycheck_code={code!r}", ps)

        # Heuristic 2: shared paycheck_code_maz (Maz)
        for code, ps in maz_map.items():
            if len(ps) >= 2:
                _add_cluster(f"shared paycheck_code_maz={code!r}", ps)

        # Heuristic 3: similar names (Levenshtein < 3)
        for p1, p2 in combinations(persons, 2):
            n1 = _normalise(p1.full_name)
            n2 = _normalise(p2.full_name)
            dist = _levenshtein(n1, n2)
            if 0 < dist < 3:
                ids = frozenset({p1.person_id, p2.person_id})
                if not _is_family_pool(ids):
                    # Only add if not already covered
                    already = any(ids.issubset(s) for s in seen_sets)
                    if not already:
                        seen_sets.append(ids)
                        clusters.append({
                            "reason": f"similar names (distance={dist}): {p1.full_name!r} vs {p2.full_name!r}",
                            "persons": [p1, p2],
                        })

        if not clusters:
            _logger.info("No duplicate candidates found.")
            if args.csv:
                print("cluster_id,reason,person_id,name,rides,paycheck_code,paycheck_code_maz,active")
            return

        _logger.info("Found %d candidate cluster(s).", len(clusters))

        if args.csv:
            _output_csv(clusters, ride_counts)
        else:
            _output_report(clusters, ride_counts)

    finally:
        db.close()


def _row_summary(p: "Person", ride_counts: dict[int, int]) -> str:  # type: ignore[name-defined]
    rides = ride_counts.get(p.person_id, 0)
    code_a = p.paycheck_code or "—"
    code_m = p.paycheck_code_maz or "—"
    active = "active" if p.active else "inactive"
    return (
        f"  pid={p.person_id:>4}  {p.full_name:<40}  "
        f"rides={rides:>4}  acumen={code_a:<6}  maz={code_m:<6}  [{active}]"
    )


def _output_report(clusters: list[dict], ride_counts: dict[int, int]) -> None:
    lines = []
    lines.append("=" * 80)
    lines.append("DUPLICATE PERSON AUDIT REPORT — READ ONLY")
    lines.append(f"Total candidate clusters: {len(clusters)}")
    lines.append("=" * 80)
    for i, cluster in enumerate(clusters, 1):
        lines.append(f"\nCluster {i}: {cluster['reason']}")
        lines.append("-" * 60)
        for p in cluster["persons"]:
            lines.append(_row_summary(p, ride_counts))
    lines.append("\n" + "=" * 80)
    lines.append("ACTION REQUIRED: Review each cluster above.")
    lines.append("If duplicates confirmed, open a separate PR to merge rows.")
    lines.append("This script NEVER modifies data.")
    lines.append("=" * 80)
    print("\n".join(lines))


def _output_csv(clusters: list[dict], ride_counts: dict[int, int]) -> None:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([
        "cluster_id", "reason", "person_id", "name",
        "rides_all_time", "paycheck_code", "paycheck_code_maz", "active"
    ])
    for i, cluster in enumerate(clusters, 1):
        for p in cluster["persons"]:
            writer.writerow([
                i,
                cluster["reason"],
                p.person_id,
                p.full_name,
                ride_counts.get(p.person_id, 0),
                p.paycheck_code or "",
                p.paycheck_code_maz or "",
                "yes" if p.active else "no",
            ])
    print(out.getvalue(), end="")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Audit duplicate person rows (read-only)")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Does nothing. Safety flag. Merging requires a separate reviewed PR.",
    )
    parser.add_argument(
        "--csv",
        action="store_true",
        help="Output candidate clusters as CSV to stdout.",
    )
    args = parser.parse_args()
    main(args)
