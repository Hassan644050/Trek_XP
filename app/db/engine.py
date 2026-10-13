from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from functools import lru_cache
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.config import get_database_settings
from app.exceptions.exceptions import DatabaseNotConfiguredException


# libpq options Neon puts in its connection string that asyncpg does not
# accept as URL parameters. sslmode is translated; the rest are dropped.
_LIBPQ_ONLY_PARAMS = {"sslmode", "channel_binding"}


@dataclass
class EngineConfig:
    url: str
    connect_args: dict = field(default_factory=dict)
    # Neon's pooled endpoint is PgBouncer in transaction mode, which cannot
    # keep a client-side pool of its own connections usefully.
    use_null_pool: bool = False


def build_engine_config(database_url: str) -> EngineConfig:
    """Turn a libpq-style URL (as Neon gives it) into asyncpg settings.

    Pure function so the translation is testable without a database.
    """
    parts = urlsplit(database_url)
    scheme = parts.scheme

    if scheme in ("postgres", "postgresql"):
        scheme = "postgresql+asyncpg"

    query = dict(parse_qsl(parts.query))
    sslmode = query.get("sslmode")
    kept = {k: v for k, v in query.items() if k not in _LIBPQ_ONLY_PARAMS}

    connect_args: dict = {}

    if sslmode and sslmode != "disable":
        # asyncpg accepts the libpq sslmode names directly.
        connect_args["ssl"] = sslmode

    pooled = "-pooler" in (parts.hostname or "")

    if pooled:
        # PgBouncer hands each transaction to any backend, so a prepared
        # statement named on one connection may not exist on the next.
        # Unique names and no caching avoid "prepared statement does not
        # exist" errors (see SQLAlchemy's asyncpg + PgBouncer notes).
        connect_args["statement_cache_size"] = 0
        connect_args["prepared_statement_cache_size"] = 0
        connect_args["prepared_statement_name_func"] = (
            lambda: f"__asyncpg_{uuid4()}__"
        )

    url = urlunsplit((scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment))

    return EngineConfig(url=url, connect_args=connect_args, use_null_pool=pooled)


def create_engine_from_url(database_url: str) -> AsyncEngine:
    config = build_engine_config(database_url)

    if config.use_null_pool:
        return create_async_engine(
            config.url, connect_args=config.connect_args, poolclass=NullPool
        )

    return create_async_engine(
        config.url,
        connect_args=config.connect_args,
        # Neon suspends idle databases and drops their connections, so
        # check each pooled connection before use and recycle old ones.
        pool_pre_ping=True,
        pool_recycle=300,
    )


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    url = get_database_settings().url

    if not url:
        raise DatabaseNotConfiguredException(
            "DATABASE_URL is not set; the coordinator area needs a database."
        )

    return create_engine_from_url(url)


@lru_cache(maxsize=1)
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request, rolled back on error."""
    async with get_sessionmaker()() as session:
        yield session
