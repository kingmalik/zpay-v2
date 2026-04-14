"""add sops + tasks for Team OS Phase 2

Revision ID: y4z5a6b7c8d9
Revises: x3y4z5a6b7c8
Create Date: 2026-04-14

Phase 2 of the Team OS rollout. Creates:
  - sop              — standard operating procedures (how-to docs)
  - sop_field_note   — per-user notes on SOPs, promotable by admin
  - task             — delegable work items assigned to team members
  - task_checklist_item
  - task_comment

Also seeds five starter SOPs and one starter task (A2P 10DLC registration
assigned to Mom, linked to the A2P SOP).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "y4z5a6b7c8d9"
down_revision: Union[str, Sequence[str], None] = "x3y4z5a6b7c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ── Seed SOP content ──────────────────────────────────────────

SOP_SEEDS = [
    {
        "title": "Register Twilio A2P 10DLC",
        "category": "admin",
        "owner_role": "operator",
        "trigger_when": "Before any SMS alerts can go out to drivers — one-time setup.",
        "content": """# Register Twilio A2P 10DLC

**Why this matters:** Without A2P 10DLC registration, Twilio silently drops SMS to US carriers. Our trip monitor currently only reaches Malik via voice calls because SMS fails.

## Steps

1. Log into Twilio Console → Messaging → Regulatory Compliance → A2P 10DLC.
2. Create a Brand (business identity):
   - Legal name: MAZ Services
   - EIN / Tax ID: *(ask Malik)*
   - Business website: *(ask Malik — can be a simple landing page)*
   - Contact email: malik@mazservices.com
3. Create a Campaign:
   - Use case: **Account Notifications** (low volume, T-Mobile safe)
   - Sample messages:
     - "MAZ Alert: Trip #1234 declined. Please call dispatch."
     - "MAZ: Please confirm driver assignment for Route 06."
   - Opt-in language: drivers consent during onboarding.
4. Wait for approval (hours to ~1 week).
5. Once approved, verify with a test SMS to Malik's phone.
6. Mark this task done and notify Malik.

## Field tips
- Keep message samples short + opt-out friendly ("Reply STOP to unsubscribe.").
- If rejected, Twilio usually tells you exactly what to change — fix + resubmit same day.
""",
    },
    {
        "title": "Weekly Payroll Batch Upload",
        "category": "payroll",
        "owner_role": "operator",
        "trigger_when": "Every Monday after FirstAlt + EverDriven files arrive.",
        "content": """# Weekly Payroll Batch Upload

## Files you need
- **FirstAlt Acumen** — CSV from partner portal
- **EverDriven** — CSV from partner portal
- Both should be for the same week ending Sunday.

## Steps
1. Log in to Z-Pay → Payroll → Upload Files.
2. Select source (FirstAlt or EverDriven), pick the CSV, click Upload.
3. Repeat for the other partner.
4. Go to Payroll → Workflow — verify batch totals match the partner portal.
5. Check for driver mismatches (unmatched names).
6. Apply to Paychex.

## Watch out for
- **EverDriven cancellations inside 2hrs = half pay.** Flag any that weren't applied.
- **Route numbers = separate accounts** — do not merge across route numbers even if driver name matches.
- **z_rate=0** on any row = rate config missing for that route. Fix before applying.
""",
    },
    {
        "title": "Handling a Declined Trip (Substitute Needed)",
        "category": "dispatch",
        "owner_role": "operator",
        "trigger_when": "Trip monitor alerts — driver declines or doesn't confirm.",
        "content": """# Handling a Declined Trip

## What the system does automatically
- Monitor calls the assigned driver.
- If declined, monitor calls Malik.
- Malik gets the decline in alerts.

## What you do
1. Open Dispatch → Live Dispatch. Find the trip.
2. Pick a substitute from the driver list (sorted by proximity + availability).
3. Click Reassign. System calls the new driver.
4. Confirm the substitute accepted.
5. Note the substitution in batch notes (for payroll reconciliation).

## Escalation
- If 2 subs decline, text Malik directly. Don't keep auto-calling.
""",
    },
    {
        "title": "Adding a New Driver (FirstAlt + EverDriven)",
        "category": "onboarding",
        "owner_role": "operator",
        "trigger_when": "New hire joins the network.",
        "content": """# Adding a New Driver

## Prerequisites
- Driver has completed FirstAlt onboarding (primary portal).
- Driver has passed drug test with Donna at Concentra.

## Steps in Z-Pay
1. Go to People → All Drivers → Add New.
2. Fill in:
   - Full name (exact match to FirstAlt)
   - FA ID + ED ID (if applicable)
   - Phone, email, home address
   - Vehicle info
   - Paycheck code (from Paychex after setup)
3. Save.
4. Send invite token via People → Onboarding.
5. Driver opens `/join/{token}` and confirms language + contact prefs.

## After onboarding
- Verify driver appears on next payroll batch.
- Confirm they can receive calls from the trip monitor.
""",
    },
    {
        "title": "Monthly Reconciliation",
        "category": "payroll",
        "owner_role": "admin",
        "trigger_when": "Last business day of each month.",
        "content": """# Monthly Reconciliation

## Goal
Every trip in partner CSVs maps to a paid row in our batch, and every paid row maps back to a trip.

## Steps
1. Z-Pay → Reconciliation. Select month.
2. Review unmatched rows:
   - Trips in partner CSV but not in our batch → missing payroll row.
   - Rows in our batch but not in partner CSV → overpayment risk.
3. Fix each mismatch, re-run.
4. Flag anomalies for next batch's makeup payment.

## Known pattern
- Batch 55 Scenic Hill ES OB ODT 06 underpayment → makeup due next batch. Track until resolved.
""",
    },
]


def upgrade() -> None:
    # ── sop ────────────────────────────────────────────────────
    op.create_table(
        "sop",
        sa.Column("sop_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("category", sa.Text, nullable=True),
        sa.Column("owner_role", sa.Text, nullable=False, server_default=sa.text("'operator'")),
        sa.Column("trigger_when", sa.Text, nullable=True),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default=sa.text("1")),
        sa.Column("created_by", sa.Integer, sa.ForeignKey("user_account.user_id"), nullable=True),
        sa.Column("updated_by", sa.Integer, sa.ForeignKey("user_account.user_id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("archived", sa.Boolean, nullable=False, server_default=sa.text("false")),
    )
    op.create_index("ix_sop_category", "sop", ["category"])
    op.create_index("ix_sop_archived", "sop", ["archived"])

    # ── sop_field_note ─────────────────────────────────────────
    op.create_table(
        "sop_field_note",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("sop_id", sa.Integer, sa.ForeignKey("sop.sop_id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_user_id", sa.Integer, sa.ForeignKey("user_account.user_id"), nullable=False),
        sa.Column("note", sa.Text, nullable=False),
        sa.Column("promoted", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_sop_field_note_sop", "sop_field_note", ["sop_id"])

    # ── task ───────────────────────────────────────────────────
    op.create_table(
        "task",
        sa.Column("task_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("assignee_id", sa.Integer, sa.ForeignKey("user_account.user_id"), nullable=True),
        sa.Column("created_by", sa.Integer, sa.ForeignKey("user_account.user_id"), nullable=True),
        sa.Column("priority", sa.Text, nullable=False, server_default=sa.text("'normal'")),
        sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'todo'")),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("linked_sop_id", sa.Integer, sa.ForeignKey("sop.sop_id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_task_assignee", "task", ["assignee_id"])
    op.create_index("ix_task_status", "task", ["status"])

    # ── task_checklist_item ────────────────────────────────────
    op.create_table(
        "task_checklist_item",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.Integer, sa.ForeignKey("task.task_id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.Text, nullable=False),
        sa.Column("done", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("order_index", sa.Integer, nullable=False, server_default=sa.text("0")),
    )
    op.create_index("ix_task_checklist_task", "task_checklist_item", ["task_id"])

    # ── task_comment ───────────────────────────────────────────
    op.create_table(
        "task_comment",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.Integer, sa.ForeignKey("task.task_id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_user_id", sa.Integer, sa.ForeignKey("user_account.user_id"), nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_task_comment_task", "task_comment", ["task_id"])

    # ── Seed content ───────────────────────────────────────────
    conn = op.get_bind()

    # Insert SOPs, remember the A2P one's id for the seed task.
    a2p_sop_id = None
    for seed in SOP_SEEDS:
        result = conn.execute(
            sa.text(
                """
                INSERT INTO sop (title, category, owner_role, trigger_when, content)
                VALUES (:title, :category, :owner_role, :trigger_when, :content)
                RETURNING sop_id
                """
            ),
            seed,
        )
        row = result.fetchone()
        if row and seed["title"].startswith("Register Twilio A2P"):
            a2p_sop_id = row[0]

    # Seed task — only if we can resolve Mom's user_id.
    mom = conn.execute(
        sa.text("SELECT user_id FROM user_account WHERE username = :u LIMIT 1"),
        {"u": "mom"},
    ).fetchone()
    malik = conn.execute(
        sa.text("SELECT user_id FROM user_account WHERE username = :u LIMIT 1"),
        {"u": "malik"},
    ).fetchone()

    if mom and a2p_sop_id:
        task_row = conn.execute(
            sa.text(
                """
                INSERT INTO task (title, description, assignee_id, created_by, priority, status, linked_sop_id)
                VALUES (:title, :description, :assignee_id, :created_by, :priority, :status, :linked_sop_id)
                RETURNING task_id
                """
            ),
            {
                "title": "Register Twilio A2P 10DLC",
                "description": (
                    "SMS alerts are currently silently failing because we're not registered. "
                    "Follow the linked SOP and ping Malik when it's submitted."
                ),
                "assignee_id": mom[0],
                "created_by": malik[0] if malik else None,
                "priority": "high",
                "status": "todo",
                "linked_sop_id": a2p_sop_id,
            },
        )
        task_id = task_row.fetchone()[0]

        checklist = [
            "Log into Twilio Console",
            "Create Brand (MAZ Services)",
            "Create Campaign with sample messages",
            "Submit for approval",
            "Verify test SMS once approved",
            "Notify Malik and mark done",
        ]
        for i, label in enumerate(checklist):
            conn.execute(
                sa.text(
                    """
                    INSERT INTO task_checklist_item (task_id, label, order_index)
                    VALUES (:task_id, :label, :order_index)
                    """
                ),
                {"task_id": task_id, "label": label, "order_index": i},
            )


def downgrade() -> None:
    op.drop_index("ix_task_comment_task", table_name="task_comment")
    op.drop_table("task_comment")
    op.drop_index("ix_task_checklist_task", table_name="task_checklist_item")
    op.drop_table("task_checklist_item")
    op.drop_index("ix_task_status", table_name="task")
    op.drop_index("ix_task_assignee", table_name="task")
    op.drop_table("task")
    op.drop_index("ix_sop_field_note_sop", table_name="sop_field_note")
    op.drop_table("sop_field_note")
    op.drop_index("ix_sop_archived", table_name="sop")
    op.drop_index("ix_sop_category", table_name="sop")
    op.drop_table("sop")
