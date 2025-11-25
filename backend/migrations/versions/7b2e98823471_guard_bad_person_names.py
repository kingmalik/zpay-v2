"""guard bad person names

Revision ID: 7b2e98823471
Revises: f340a39c325a
Create Date: 2025-09-28 08:28:59.253142

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7b2e98823471'
down_revision: Union[str, Sequence[str], None] = 'f340a39c325a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
