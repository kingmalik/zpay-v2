"""add intake_submitted_at to onboarding_record

Revision ID: zn2o3p4q5r6s
Revises: zm1n2o3p4q5r
Create Date: 2026-05-04

Fixes compliance cron UndefinedColumn error — onboarding_monitor was querying
onboarding_record.intake_submitted_at which was declared in models.py but never
had a corresponding migration. One cron error per 30-min cycle since column was
added to the model.
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "zn2o3p4q5r6s"
down_revision: Union[str, None] = "zm1n2o3p4q5r"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "onboarding_record",
        sa.Column("intake_submitted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("onboarding_record", "intake_submitted_at")
