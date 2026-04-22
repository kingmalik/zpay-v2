"""move drug_test columns from person to onboarding_record

Revision ID: za1b2c3d4e5f6
Revises: drug1test2consent
Create Date: 2026-04-22
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "za1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "drug1test2consent"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add columns to onboarding_record
    op.add_column('onboarding_record', sa.Column('drug_test_agreement_id', sa.Text(), nullable=True))
    op.add_column('onboarding_record', sa.Column('drug_test_sent_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('onboarding_record', sa.Column('drug_test_signed_at', sa.DateTime(timezone=True), nullable=True))

    # Backfill from person table where onboarding_record exists
    op.execute("""
        UPDATE onboarding_record
        SET
            drug_test_agreement_id = p.drug_test_agreement_id,
            drug_test_sent_at = p.drug_test_sent_at,
            drug_test_signed_at = p.drug_test_signed_at
        FROM person p
        WHERE onboarding_record.person_id = p.person_id
          AND p.drug_test_agreement_id IS NOT NULL;
    """)


def downgrade() -> None:
    # Drop columns from onboarding_record (rollback)
    op.drop_column('onboarding_record', 'drug_test_signed_at')
    op.drop_column('onboarding_record', 'drug_test_sent_at')
    op.drop_column('onboarding_record', 'drug_test_agreement_id')
