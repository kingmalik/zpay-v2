# alembic/versions/20251005_add_person_code.py
from alembic import op
import sqlalchemy as sa

# Replace with your own generated IDs if you use `alembic revision -m`
revision = "add_person_code_20251005"
down_revision = "ce2f8e75441e"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("person", sa.Column("code", sa.String(length=50), nullable=True))
    op.create_index("ix_person_code", "person", ["code"], unique=False)

    # OPTIONAL: backfill from ride table if it has a code column
    # op.execute("""
    #     UPDATE person p
    #     SET code = sub.code
    #     FROM (
    #         SELECT person_id, MAX(code) AS code
    #         FROM ride
    #         WHERE code IS NOT NULL
    #         GROUP BY person_id
    #     ) sub
    #     WHERE p.person_id = sub.person_id
    # """)

def downgrade():
    op.drop_index("ix_person_code", table_name="person")
    op.drop_column("person", "code")
