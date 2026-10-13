"""Access rules that hold before any database query runs."""

import pytest

from app.db import engine as engine_module
from app.db.engine import get_db
from app.main import app

CSRF = {"X-Requested-With": "trekxp"}


@pytest.fixture
def no_db():
    # Requests rejected by these rules never touch the session, so a
    # placeholder is enough -- and proves no query was needed to refuse.
    async def placeholder():
        yield object()

    app.dependency_overrides[get_db] = placeholder
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/auth/me"),
        ("GET", "/api/coordinator/options"),
        ("GET", "/api/coordinator/gadgets"),
        ("GET", "/api/coordinator/gadgets/1"),
        ("GET", "/api/coordinator/places?q=kaptai"),
        ("GET", "/api/admin/users"),
    ],
)
def test_signed_out_reads_are_refused(client, no_db, method, path):
    response = client.request(method, path)
    assert response.status_code == 401
    assert response.json() == {"detail": "Please sign in."}


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/auth/login"),
        ("POST", "/api/auth/logout"),
        ("POST", "/api/coordinator/gadgets"),
        ("PATCH", "/api/coordinator/gadgets/1"),
        ("DELETE", "/api/coordinator/gadgets/1"),
        ("DELETE", "/api/coordinator/placements/1"),
        ("POST", "/api/admin/users"),
    ],
)
def test_writes_without_the_verification_header_are_refused(client, no_db, method, path):
    body = {"email": "a@b.co", "password": "x" * 10} if path.endswith("login") else None
    response = client.request(method, path, json=body)

    assert response.status_code == 403
    assert response.json() == {"detail": "Missing request verification header."}


def test_signed_out_write_with_header_is_401_not_403(client, no_db):
    response = client.post("/api/coordinator/gadgets", json={"name": "Dry bag"}, headers=CSRF)
    assert response.status_code == 401


def test_coordinator_page_is_served(client):
    response = client.get("/coordinator")
    assert response.status_code == 200
    assert "Coordinator sign in" in response.text


def test_missing_database_gives_a_clean_503(client, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    engine_module.get_engine.cache_clear()
    engine_module.get_sessionmaker.cache_clear()

    try:
        response = client.get("/api/auth/me")
    finally:
        engine_module.get_engine.cache_clear()
        engine_module.get_sessionmaker.cache_clear()

    assert response.status_code == 503
    assert response.json() == {"detail": "The coordinator area is not available right now."}
