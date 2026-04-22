"""add drug test consent columns to person table

Revision ID: drug1test2consent
Revises: h9i0j1k2l3m4
Create Date: 2026-04-22
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "drug1test2consent"
down_revision: Union[str, Sequence[str], None] = "h9i0j1k2l3m4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("person", sa.Column("drug_test_agreement_id", sa.Text(), nullable=True))
    op.add_column("person", sa.Column("drug_test_sent_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("person", sa.Column("drug_test_signed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("person", "drug_test_signed_at")
    op.drop_column("person", "drug_test_sent_at")
    op.drop_column("person", "drug_test_agreement_id")
