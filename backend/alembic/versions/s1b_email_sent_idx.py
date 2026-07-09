"""add_partial_unique_index_email_send_log_sent_once

Revision ID: s1b_email_sent_idx
Revises: s1a_paychex_job
Create Date: 2026-07-08

Rationale:
  S1 Monday-proofing: stub-send idempotency. A partial unique index on
  (payroll_batch_id, person_id) WHERE status='sent' AND is_test=false
  guarantees at the DB layer that a driver can never end up with two real
  "sent" EmailSendLog rows for the same batch — the failure mode that would
  otherwise 500 mid-payroll-send if two overlapping requests (or a resend
  racing an in-flight send) both tried to record success.

  Application code in backend/routes/workflow.py (send-stubs, resend-stubs,
  send-stub, retry-stub) now deletes any prior real "sent" row for the
  (batch, person) pair before inserting a new one, so this index should
  never actually be violated in the normal path — it's a backstop.

  CONCURRENTLY note:
    This repo's alembic env.py (backend/alembic/env.py) wraps migrations in
    a single context.begin_transaction() with no per-migration autocommit
    block, and no prior migration in this repo uses CREATE INDEX
    CONCURRENTLY. CONCURRENTLY cannot run inside a transaction, so it is
    intentionally omitted here — email_send_log is a small operational
    table (one row per stub send), so a brief lock during index build is
    not a practical concern.

  Online-safe:
    - IF NOT EXISTS guards re-runs.
    - Partial index only touches 'sent'/is_test=false rows — small subset.
    - Fully reversible via downgrade().
"""

from __future__ import annotations

from typing import Union

from alembic import op

# ── revision identifiers ──────────────────────────────────────────────────────
revision: str = "s1b_email_sent_idx"
down_revision: Union[str, None] = "s1a_paychex_job"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Dedup first: prod has at least one historical duplicate (batch 87 /
    # person 46 — manual stub resend during the May 2026 recovery). Keep the
    # newest row per (batch, person); the index build would otherwise fail
    # at deploy time and crash-loop the release.
    op.execute(
        """
        DELETE FROM email_send_log e
        USING email_send_log newer
        WHERE e.status = 'sent' AND e.is_test = false
          AND newer.status = 'sent' AND newer.is_test = false
          AND newer.payroll_batch_id = e.payroll_batch_id
          AND newer.person_id = e.person_id
          AND newer.id > e.id
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_email_sent_once
        ON email_send_log (payroll_batch_id, person_id)
        WHERE status = 'sent' AND is_test = false
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_email_sent_once")
