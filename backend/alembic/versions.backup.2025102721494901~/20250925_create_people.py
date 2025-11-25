"""create people table"""

from alembic import op
import sqlalchemy as sa

# If this is your first migration, keep None. Otherwise set to your last revision id.
revision = "20250927_create_people"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "people",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(length=50), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("code", name="uq_people_code"),
        sa.UniqueConstraint("email", name="uq_people_email"),
    )

    # Updated-at trigger (PostgreSQL) so updated_at auto-refreshes on UPDATE
    op.execute("""
    CREATE OR REPLACE FUNCTION set_updated_at() RETURNS TRIGGER AS $$
    BEGIN
      NEW.updated_at = NOW();
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """)

    op.execute("""
    CREATE TRIGGER people_set_updated_at
    BEFORE UPDATE ON people
    FOR EACH ROW
    EXECUTE PROCEDURE set_updated_at();
    """)

    # Optional seed rows so your /people endpoint shows something
    op.execute("""
    INSERT INTO people (code, name, email)
    VALUES
      ('P001','Jane Doe','jane@example.com'),
      ('P002','John Lee','john@example.com');
    """)


def downgrade():
    # Drop trigger & function first (IF EXISTS for safety)
    op.execute("DROP TRIGGER IF EXISTS people_set_updated_at ON people;")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at();")
    op.drop_table("people")

