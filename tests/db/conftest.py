"""Fixtures for tests that need a real PostgreSQL database.

Skipped unless TEST_DATABASE_URL is set (in the environment or .env).
Point it at a disposable database -- e.g. a Neon branch named "test" --
because every test empties the tables it uses.
"""

import asyncio
import os

import pytest
from alembic import command
from alembic.config import Config
from dotenv import load_dotenv
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.auth.passwords import hash_password
from app.config import PROJECT_ROOT
from app.db.engine import build_engine_config, get_db
from app.db.models import Role, User
from app.main import app
from app.services.media.storage import LocalImageStorage


load_dotenv()

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
CSRF = {"X-Requested-With": "trekxp"}
PASSWORD = "correct horse battery"
TABLES = "placements, gadgets, places, auth_sessions, users"


def pytest_collection_modifyitems(config, items):
    if TEST_DATABASE_URL:
        return

    skip = pytest.mark.skip(reason="TEST_DATABASE_URL not set; database tests skipped")
    for item in items:
        if "tests/db/" in str(item.fspath).replace(os.sep, "/"):
            item.add_marker(skip)


def _engine():
    # NullPool: TestClient runs the app on its own event loop, and asyncpg
    # connections cannot move between loops, so never reuse one.
    config = build_engine_config(TEST_DATABASE_URL)
    return create_async_engine(config.url, connect_args=config.connect_args, poolclass=NullPool)


def run(coro_fn):
    """Run an async helper with a throwaway engine, from sync test code."""

    async def wrapper():
        engine = _engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                return await coro_fn(session)
        finally:
            await engine.dispose()

    return asyncio.run(wrapper())


@pytest.fixture(scope="session")
def migrated():
    if TEST_DATABASE_URL == os.getenv("DATABASE_URL"):
        pytest.exit(
            "TEST_DATABASE_URL is the same as DATABASE_URL. Refusing to run: "
            "the database tests delete data. Use a separate Neon branch.",
            returncode=2,
        )

    os.environ["MIGRATION_DATABASE_URL"] = TEST_DATABASE_URL
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    command.upgrade(config, "head")
    yield config
    os.environ.pop("MIGRATION_DATABASE_URL", None)


@pytest.fixture
def db_app(migrated, tmp_path, monkeypatch):
    """The app wired to the test database and a temporary image folder."""

    async def truncate(session):
        await session.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
        await session.commit()

    run(truncate)

    engine = _engine()
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def test_db():
        async with sessions() as session:
            yield session

    storage = LocalImageStorage(tmp_path / "media", "/media")
    app.dependency_overrides[get_db] = test_db
    monkeypatch.setattr("app.routes.coordinator.get_image_storage", lambda: storage)
    monkeypatch.setenv("MAX_FAILED_LOGINS", "3")
    monkeypatch.setenv("COOKIE_SECURE", "false")

    yield storage

    app.dependency_overrides.pop(get_db, None)
    asyncio.run(engine.dispose())


def make_user(email, role=Role.COORDINATOR, name="Test User", active=True, password=PASSWORD):
    async def create(session):
        user = User(
            email=email, name=name, role=role, is_active=active,
            password_hash=hash_password(password),
        )
        session.add(user)
        await session.commit()
        return user.id

    return run(create)


def signed_in(email, password=PASSWORD) -> TestClient:
    """A browser with its own cookie jar, signed in as the given user."""
    client = TestClient(app)
    response = client.post("/api/auth/login", json={"email": email, "password": password}, headers=CSRF)
    assert response.status_code == 200, response.text
    return client


@pytest.fixture
def admin(db_app):
    make_user("admin@trekxp.test", role=Role.ADMIN, name="Admin")
    return signed_in("admin@trekxp.test")


@pytest.fixture
def coordinator(db_app):
    make_user("coord@trekxp.test", name="Coordinator")
    return signed_in("coord@trekxp.test")
