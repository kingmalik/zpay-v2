# alembic/versions/202510292109_add_service_name_and_person_code.py
from alembic import op
import sqlalchemy as sa

revision = "202510292109"
down_revision = "ce2f8e75441e"

def upgrade():
    # add 'service_name' to ride
    op.add_column("ride", sa.Column("service_name", sa.Text(), nullable=True))
    # add 'person_code' to person (optional but matches your report)
    op.add_column("person", sa.Column("person_code", sa.Text(), nullable=True))
    op.create_unique_constraint("person_person_code_uniq", "person", ["person_code"])

def downgrade():
    op.drop_constraint("person_person_code_uniq", "person", type_="unique")
    op.drop_column("person", "person_code")
    op.drop_column("ride", "service_name")
