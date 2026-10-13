import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection

from app.config import get_database_settings
from app.db.engine import create_engine_from_url
from app.db.models import Base


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    # MIGRATION_DATABASE_URL lets you point migrations at another database
    # (e.g. a Neon test branch) without editing .env.
    url = os.getenv("MIGRATION_DATABASE_URL") or get_database_settings().url

    if not url:
        raise RuntimeError("Set DATABASE_URL in .env before running migrations.")

    return url


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of connecting (alembic upgrade --sql)."""
    context.configure(
        url="postgresql://",
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    # Same URL translation as the app, so Neon strings work unchanged.
    engine = create_engine_from_url(_database_url())

    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
