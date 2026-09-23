"""dedupe z_rate_service — soft-merge duplicate (source, canonical service_name) rows.

Revision ID: s14_dedupe_z_rate_service
Revises: s13_batch_rate_decision
Create Date: 2026-09-23

Background
----------
`z_rate_service` had a unique index on (source, company_name, service_name),
but company_name was never a reliable key — the same route was imported over
time under several spellings ("FirstAlt" / "Acumen International" / "Acumen",
"EverDriven" / "everDriven"). That left duplicate rows per (source,
service_name), 53 of which carried different default_rate values — plus a
handful that duplicate again purely by whitespace (a double space in the
service_name). Payroll pricing (backend/services/recalculate.py) and the
"Permanent" rate-edit button (backend/routes/api_data.py POST
/rides/{id}/set-rate) both now key off (source, service_name) among ACTIVE
rows only — this migration soft-merges the duplicates down to one ACTIVE row
per (source, canonicalized service_name), then adds the enforcing partial
expression index.

Nothing is ever hard-deleted (2026-09-23, Malik). A "loser" row is
deactivated (active=false) and pointed at the survivor via merged_into_id —
every other column on it (default_rate, company_name, ...) is left exactly
as it was, so the merge is fully reversible by hand if ever needed.

Survivor ROW (FK continuity): most `ride.z_rate_service_id` references wins;
ties go to the lowest z_rate_service_id. FK references
(ride.z_rate_service_id, z_rate_override.z_rate_service_id) are repointed to
the survivor before the losers are deactivated.

Rule A (grouping + index): duplicates are grouped by
(source, canonicalize(service_name)) — canonicalize collapses whitespace
runs and lowercases, done in Python (backend/services/rate_service_dedupe.py
canonical_service_name()) so it's dialect-independent. The survivor keeps
its own raw name, with internal whitespace runs on ITS OWN name collapsed to
single spaces. The DB-level constraint mirrors this with a Postgres
EXPRESSION partial unique index — not representable as a portable
SQLAlchemy Index() (SQLite has no regexp_replace) — so it's created here via
raw SQL, and the model (backend/db/models.py) carries only a comment.

Rule B (label normalization): the survivor's company_name is normalized to
whatever label current batches use for its source (most recent
PayrollBatch.company_name for that source; falls back to 'FirstAlt'/acumen,
'EverDriven'/maz). admin_rates.py, excell_reader.py and pdf_reader.py still
filter by company_name == batch.company_name in places, so this keeps those
working on day one.

Rule C: late_cancellation_rate carries from a loser to the survivor when the
survivor doesn't have one of its own (highest loser id wins on a tie).

Survivor RATE (2026-09-23 real-data finding, refined same day): FK reference
count is NOT a reliable signal for which rate drivers were actually paid —
the import-time resolver (backend/services/rates.py) picks a row by
company_name label, not by FK. So the survivor's default_rate is separately
set to the "last paid" rate — the mode of ride.z_rate among *qualifying*
rides (route-level pricing sources only, no late-cancel-shaped rides,
matched by name not FK) in the most recent batch that has any, but ONLY
when that signal is CONFIRMED (>=2 rides at that rate in the batch, or the
prior qualifying batch agrees). An UNCLEAR signal (e.g. one single
special-priced ride) leaves the stored rate untouched. See
backend/services/rate_service_dedupe.py for the exact rule and its tests.

Rule D: if the survivor's default_rate is still NULL/0 after the last-paid
rule (i.e. that signal wasn't confirmed), and a loser has a non-zero rate,
the survivor adopts the highest such loser rate — a stub must never win over
a real rate.

Every meaningful change (merge, rate change, label normalization, LC-rate
carry, zero-rate rescue, own-name whitespace cleanup) writes an AuditLog row
(actions prefixed "rate_dedupe_") so it's traceable.

Idempotent: a second run finds no duplicate ACTIVE groups (the first run's
losers are already inactive) and only re-creates the column/index if
missing (no-op if present).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.orm import Session

revision: str = "s14_dedupe_z_rate_service"
down_revision: Union[str, None] = "s13_batch_rate_decision"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Rule A: Postgres-only expression index (regexp_replace has no SQLite
# equivalent), so it's raw SQL rather than op.create_index(). IF NOT EXISTS
# / IF EXISTS make both directions idempotent.
_CANON_INDEX_NAME = "uq_z_rate_service_source_canon_name_active"
_CANON_INDEX_CREATE_SQL = (
    f"CREATE UNIQUE INDEX IF NOT EXISTS {_CANON_INDEX_NAME} "
    "ON z_rate_service (source, lower(regexp_replace(service_name, '\\s+', ' ', 'g'))) "
    "WHERE active = true"
)
_CANON_INDEX_DROP_SQL = f"DROP INDEX IF EXISTS {_CANON_INDEX_NAME}"


def upgrade() -> None:
    from backend.services.rate_service_dedupe import dedupe_all, normalize_all_active_labels

    conn = op.get_bind()

    # merged_into_id must exist before dedupe_all runs (it writes to it).
    # Guard against a re-run after a partial failure.
    inspector = sa.inspect(conn)
    existing_cols = {c["name"] for c in inspector.get_columns("z_rate_service")}
    if "merged_into_id" not in existing_cols:
        op.add_column(
            "z_rate_service",
            sa.Column(
                "merged_into_id",
                sa.Integer(),
                sa.ForeignKey("z_rate_service.z_rate_service_id", ondelete="SET NULL"),
                nullable=True,
            ),
        )

    # The original uq_z_rate_service_scope (source, company_name,
    # service_name) index was NOT partial. Rule B (company_name label
    # normalization, below) updates an ACTIVE survivor's company_name to
    # whatever label an already-INACTIVE (soft-merged) loser row may
    # already carry — a non-partial index would reject that update. Convert
    # it to partial BEFORE dedupe_all runs. This must happen every run (not
    # guarded by a column-exists check) but DROP/CREATE ... IF [NOT] EXISTS
    # makes it idempotent on its own.
    # Its partial replacement is created AFTER the merge (below), once the
    # losers are inactive — creating it here collides on a re-run after a
    # downgrade (verified on a production copy 2026-09-23).
    op.execute(sa.text("DROP INDEX IF EXISTS uq_z_rate_service_scope"))

    session = Session(bind=conn)
    try:
        results = dedupe_all(session)
        relabeled = normalize_all_active_labels(session)
        session.commit()
    finally:
        session.close()

    print(f"[s14_dedupe_z_rate_service] merged {len(results)} duplicate group(s)")
    print(f"[s14_dedupe_z_rate_service] relabeled {len(relabeled)} never-duplicated active row(s) to the current company label")
    for r in results:
        print(
            "[s14_dedupe_z_rate_service] "
            f"source={r.source!r} service_name={r.service_name!r} "
            f"survivor_id={r.survivor_id} survivor_default_rate={r.survivor_default_rate} "
            f"merged_ids={list(r.merged_ids)} (soft-merged, active=false — not deleted) "
            f"rides_repointed={r.rides_repointed} overrides_repointed={r.overrides_repointed}"
        )
        if r.service_name_normalized:
            print(
                f"[s14_dedupe_z_rate_service] {r.service_name}: service_name whitespace "
                f"normalized {r.old_service_name!r} -> {r.service_name!r}"
            )
        if r.company_name_changed:
            print(
                f"[s14_dedupe_z_rate_service] {r.service_name}: company_name "
                f"{r.old_company_name!r} -> {r.new_company_name!r}"
            )
        if r.late_cancellation_carried:
            print(
                f"[s14_dedupe_z_rate_service] {r.service_name}: late_cancellation_rate "
                f"{r.late_cancellation_rate} carried from merged row {r.late_cancellation_source_id}"
            )
        if r.rate_changed:
            print(
                f"[s14_dedupe_z_rate_service] {r.service_name}: default_rate "
                f"{r.old_default_rate} -> {r.survivor_default_rate} (last paid, batch {r.last_paid_batch_id})"
            )
        elif r.confidence == "unclear":
            plural = "ride" if r.rides_at_that_rate == 1 else "rides"
            print(
                f"[s14_dedupe_z_rate_service] {r.service_name}: UNCLEAR — kept row rate "
                f"{r.old_default_rate}; last paid {r.last_paid_rate} in batch {r.last_paid_batch_id} "
                f"on {r.rides_at_that_rate} {plural}"
            )
        elif r.confidence == "none":
            print(f"[s14_dedupe_z_rate_service] {r.service_name}: no paid history")
        if r.zero_rate_rescued:
            print(
                f"[s14_dedupe_z_rate_service] {r.service_name}: adopted non-zero rate "
                f"from merged row {r.zero_rate_rescued_from_id}"
            )

    # Idempotent, partial, EXPRESSION unique index (Rule A) — only active
    # rows need to be unique, keyed on the canonicalized name, so two rows
    # differing only by a double space also collide correctly.
    op.execute(sa.text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_z_rate_service_scope "
        "ON z_rate_service (source, company_name, service_name) WHERE active = true"
    ))
    op.execute(sa.text(_CANON_INDEX_CREATE_SQL))


def downgrade() -> None:
    conn = op.get_bind()
    # Order matters: BOTH uniqueness indexes come off BEFORE the soft-merged
    # rows are reactivated, otherwise reactivating a loser collides with its
    # survivor (verified on a production copy 2026-09-23). The scope index is
    # NOT recreated: after label normalisation a reactivated loser and its
    # survivor can legitimately share (source, company_name, service_name),
    # so the pre-s14 non-partial index cannot be satisfied any more. The
    # next `upgrade` recreates both indexes.
    op.execute(sa.text(_CANON_INDEX_DROP_SQL))
    op.execute(sa.text("DROP INDEX IF EXISTS uq_z_rate_service_scope"))
    # Reactivate every soft-merged loser and clear the merge pointer.
    # Rate/label/late-cancellation changes made by the rules above are left
    # as-is — the AuditLog rows this migration wrote (actions prefixed
    # "rate_dedupe_") carry the old values if a manual revert is ever needed.
    conn.execute(
        sa.text(
            "UPDATE z_rate_service SET active = true, merged_into_id = NULL "
            "WHERE merged_into_id IS NOT NULL"
        )
    )
    # batch_alter_table (not a bare op.drop_column): merged_into_id is a
    # self-referential FK column, which SQLite's simplified ALTER TABLE
    # DROP COLUMN cannot handle directly ("unknown column ... in foreign
    # key definition") — it needs the full table-rebuild that batch mode
    # performs. On Postgres this compiles down to the same plain
    # ALTER TABLE ... DROP COLUMN either way.
    with op.batch_alter_table("z_rate_service") as batch_op:
        batch_op.drop_column("merged_into_id")
