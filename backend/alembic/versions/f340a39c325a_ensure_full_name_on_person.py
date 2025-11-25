"""ensure full_name on person inserts/updates"""

from alembic import op

revision = "f340a39c325a"
down_revision = '04b22dd2da82'
branch_labels = None
depends_on = None


def upgrade():
    # Create/replace the function that ensures full_name is populated
    op.execute("""
    CREATE OR REPLACE FUNCTION person_ensure_full_name() RETURNS TRIGGER AS $$
    BEGIN
      IF NEW.full_name IS NULL OR btrim(NEW.full_name) = '' THEN
        NEW.full_name := COALESCE(
          NULLIF(btrim(NEW.email), ''),
          NULLIF(btrim(NEW.external_id), ''),
          'Unknown'
        );
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """)

    # Drop any existing trigger (safe to call repeatedly)
    op.execute("DROP TRIGGER IF EXISTS trg_person_ensure_full_name ON person;")

    # Create trigger for INSERT and UPDATE
    op.execute("""
    CREATE TRIGGER trg_person_ensure_full_name
    BEFORE INSERT OR UPDATE ON person
    FOR EACH ROW
    EXECUTE FUNCTION person_ensure_full_name();
    """)

    # Clean up any existing rows with null/empty full_name (defensive)
    op.execute("""
    UPDATE person
       SET full_name = 'Unknown'
     WHERE full_name IS NULL OR btrim(full_name) = '';
    """)


def downgrade():
    op.execute("DROP TRIGGER IF EXISTS trg_person_ensure_full_name ON person;")
    op.execute("DROP FUNCTION IF EXISTS person_ensure_full_name;")
