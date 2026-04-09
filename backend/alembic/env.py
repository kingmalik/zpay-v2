import os
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

# Interpret the config file for Python logging.
config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# --- Load SQLAlchemy metadata for autogenerate (best effort) ---
# Try common locations; okay if it fails (manual migrations still work).
target_metadata = None
for path in ("backend.models", "backend.db", "backend.app.models", "backend.app.db"):
    try:
        mod = __import__(path, fromlist=["*"])
        target_metadata = getattr(mod, "Base").metadata
        break
    except Exception:
        pass

# Override DB URL from env if present
# Normalize URL to psycopg dialect (psycopg v3, installed in Docker)
db_url = os.getenv("DATABASE_URL")
if db_url:
    db_url = db_url.replace("postgresql+psycopg2://", "postgresql+psycopg://", 1)
    db_url = db_url.replace("postgres://", "postgresql+psycopg://", 1)
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+psycopg://", 1)
    config.set_main_option("sqlalchemy.url", db_url)

def run_migrations_offline():
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        future=True,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

