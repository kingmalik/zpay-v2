"""dedupe z_rate_service — merge duplicate (source, service_name) rows.

Revision ID: s14_dedupe_z_rate_service
Revises: s13_batch_rate_decision
Create Date: 2026-09-23

Background
----------
`z_rate_service` had a unique index on (source, company_name, service_name),
but company_name was never a reliable key — the same route was imported over
time under several spellings ("FirstAlt" / "Acumen International" / "Acumen",
"EverDriven" / "everDriven"). That left duplicate rows per (source,
service_name), 53 of which carried different default_rate values. Payroll
pricing (backend/services/recalculate.py) and the "Permanent" rate-edit button
(backend/routes/api_data.py POST /rides/{id}/set-rate) both now key off
(source, service_name) only — this migration merges the duplicates down to
one row per (source, service_name) so that key is actually unique, then adds
the enforcing index.

Merge logic lives in backend/services/rate_service_dedupe.py (also unit
tested there) so the survivor rule is exercised outside of a live migration
run. Survivor rule: most `ride.z_rate_service_id` references wins; ties go to
the lowest z_rate_service_id. The survivor's own default_rate is kept as-is.
FK references (ride.z_rate_service_id, z_rate_override.z_rate_service_id) are
repointed to the survivor before the loser rows are deleted.

Idempotent: a second run finds no duplicate groups (the unique index already
enforces it) and only re-creates the index if missing (no-op if present).
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy.orm import Session

revision: str = "s14_dedupe_z_rate_service"
down_revision: Union[str, None] = "s13_batch_rate_decision"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from backend.services.rate_service_dedupe import dedupe_all

    conn = op.get_bind()
    session = Session(bind=conn)
    try:
        results = dedupe_all(session)
        session.commit()
    finally:
        session.close()

    print(f"[s14_dedupe_z_rate_service] merged {len(results)} duplicate group(s)")
    for r in results:
        print(
            "[s14_dedupe_z_rate_service] "
            f"source={r.source!r} service_name={r.service_name!r} "
            f"survivor_id={r.survivor_id} survivor_default_rate={r.survivor_default_rate} "
            f"merged_ids={list(r.merged_ids)} "
            f"rides_repointed={r.rides_repointed} overrides_repointed={r.overrides_repointed}"
        )

    # Idempotent: create_index with if_not_exists so a re-run (e.g. after a
    # partial failure) doesn't blow up on an index that already exists.
    op.create_index(
        "uq_z_rate_service_source_service_name",
        "z_rate_service",
        ["source", "service_name"],
        unique=True,
        if_not_exists=True,
    )


def downgrade() -> None:
    # The merge itself is not reversible — the deleted duplicate rows and
    # which ride/override originally pointed at which of them are gone.
    # Only the enforcing index is removable.
    op.drop_index("uq_z_rate_service_source_service_name", table_name="z_rate_service", if_exists=True)
