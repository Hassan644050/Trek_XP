import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.recommendation import Recommendation
from app.services.gadgets.base import GadgetSource


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Fail loudly if any test reaches for a real service.

    The destination services use httpx.AsyncClient; TestClient uses the sync
    client, so blocking only the async one leaves the app itself reachable.
    """

    async def blocked(*args, **kwargs):
        raise RuntimeError("network access is disabled in tests")

    monkeypatch.setattr(httpx.AsyncClient, "send", blocked)

    def no_llm():
        raise RuntimeError("real LLM provider used in tests")

    monkeypatch.setattr("app.services.gadgets.llm_source.get_llm_provider", no_llm)


@pytest.fixture(autouse=True)
def fresh_osm_state(monkeypatch):
    """Isolate tests from the OpenStreetMap cache and rate limiter."""
    from app.services.destination import osm

    osm._cache.clear()
    monkeypatch.setattr(osm, "MIN_INTERVAL_SECONDS", 0.0)
    yield
    osm._cache.clear()


@pytest.fixture(autouse=True)
def no_catalog_db(monkeypatch):
    """Keep offline route tests away from a real database.

    /recommend now consults the community catalog, which opens a session.
    The dev .env sets DATABASE_URL, so without this an offline test would
    try to dial Neon. Tests that exercise the catalog patch this with their
    own match; catalog behaviour against a real database lives in tests/db.
    """
    from app.services.gadgets.catalog import CatalogMatch

    async def empty_catalog(context):
        return CatalogMatch()

    monkeypatch.setattr("app.routes.recommend._load_catalog", empty_catalog)


@pytest.fixture
def client():
    return TestClient(app)


class FakeGadgetSource(GadgetSource):
    def __init__(self, recommendations=None, error=None):
        self.recommendations = recommendations or []
        self.error = error
        self.contexts = []

    def recommend(self, context):
        self.contexts.append(context)
        if self.error is not None:
            raise self.error
        return self.recommendations


@pytest.fixture
def fake_source():
    return FakeGadgetSource(
        recommendations=[
            Recommendation(
                gadget="Universal adapter (Type A/C/D/G/K)",
                why="Bangladesh uses mixed plug types at 220V.",
                priority="essential",
                category="Power",
            ),
            Recommendation(
                gadget="Headlamp",
                why="Hands-free light for campsite setup.",
                category="Lighting",
            ),
        ]
    )


@pytest.fixture
def trip_payload():
    """A trip picked from the destination picker, so no geocoding is needed."""
    return {
        "destination": "Sylhet",
        "start_date": "2026-11-10",
        "end_date": "2026-11-14",
        "trip_type": "hiking",
        "activities": ["photography", "camping"],
        "baggage": "carry_on_only",
        "travelers": 2,
        "latitude": 24.89904,
        "longitude": 91.87198,
        "country_code": "BD",
        "country_name": "Bangladesh",
    }
