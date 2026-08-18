import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make project root importable so we can pull in our models and config.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import DATABASE_URL
from database import Base
import models  # noqa: F401 — side-effect import registers all ORM classes with Base.metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations without a live DB connection (generates SQL to stdout)."""
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live DB connection."""
    # lock_timeout via connect_args/options fires at the libpq level — before any
    # transaction begins — so it's immune to SQLAlchemy autobegin / SAVEPOINT interactions
    # that can silently swallow a SET statement issued on the connection object.
    # 10 000 ms = 10 s: if ALTER TABLE can't get its ACCESS EXCLUSIVE LOCK in that window
    # (e.g. active SSE sessions on the production server are holding transactions open),
    # Postgres raises LockNotAvailable and database.py catches it so startup continues.
    connectable = engine_from_config(
        {"sqlalchemy.url": DATABASE_URL},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # each migration run gets its own connection, no pool needed
        connect_args={"options": "-c lock_timeout=10000"},
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
