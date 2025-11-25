"""block junk person names

Revision ID: ce2f8e75441e
Revises: 7b2e98823471
Create Date: 2025-09-28 09:21:52.942384

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ce2f8e75441e'
down_revision: Union[str, Sequence[str], None] = '7b2e98823471'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
