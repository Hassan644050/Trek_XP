from app.exceptions.exceptions import (
    DestinationDataException,
    GadgetSourceException,
    LLMProviderException,
    LLMRateLimitException,
)
from app.models.context import ClimateInfo
from app.services.destination.geocode import GeoResult
from tests.conftest import FakeGadgetSource

CLIMATE_SUMMARY = "Typical conditions (same dates last year): hot and mostly dry; 17.6°C to 29.4°C."


def use_climate(monkeypatch, climate):
    async def fake_fetch_climate(**kwargs):
        return climate

    monkeypatch.setattr("app.services.destination.aggregator.fetch_climate", fake_fetch_climate)


def use_source(monkeypatch, source):
    monkeypatch.setattr("app.routes.recommend.get_gadget_source", lambda: source)


def test_health(client):
    assert client.get("/health").json() == {"status": "healthy"}


def test_frontend_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_recommend_happy_path(client, monkeypatch, fake_source, trip_payload):
    use_climate(monkeypatch, ClimateInfo(summary=CLIMATE_SUMMARY, historical=True))
    use_source(monkeypatch, fake_source)

    response = client.post("/recommend", json=trip_payload)

    assert response.status_code == 200
    body = response.json()
    assert body["destination"] == "Sylhet"
    assert body["duration_days"] == 5
    assert [r["gadget"] for r in body["recommendations"]] == [
        "Universal adapter (Type A/C/D/G/K)",
        "Headlamp",
    ]
    assert all(r["origin"] == "llm" and r["verified"] is False for r in body["recommendations"])
    assert body["sources"] == [
        "open_meteo_geocoding",
        "open_meteo_archive",
        "plug_dataset",
        "llm_gadget_knowledge",
    ]
    assert body["notes"] == [
        CLIMATE_SUMMARY,
        "Bangladesh: plug type A/C/D/G/K, 220V 50Hz.",
        "Suggestions come from a language model and have not been community-verified.",
    ]


def test_picker_coordinates_skip_geocoding(client, monkeypatch, fake_source, trip_payload):
    use_climate(monkeypatch, ClimateInfo(summary=CLIMATE_SUMMARY, historical=True))
    use_source(monkeypatch, fake_source)

    async def must_not_geocode(destination, home_country=None):
        raise AssertionError("geocoder called despite picker coordinates")

    monkeypatch.setattr("app.services.destination.aggregator.geocode", must_not_geocode)

    assert client.post("/recommend", json=trip_payload).status_code == 200
    assert fake_source.contexts[0].resolved_place == "Sylhet"


def test_missing_data_is_stated_not_hidden(client, monkeypatch, fake_source, trip_payload):
    use_climate(monkeypatch, ClimateInfo(available=False, historical=True))
    use_source(monkeypatch, fake_source)
    trip_payload.update(country_code="ZZ", country_name="Nowhere")

    body = client.post("/recommend", json=trip_payload).json()

    assert body["sources"] == ["open_meteo_geocoding", "llm_gadget_knowledge"]
    assert body["notes"][0].startswith("Climate data was unavailable")
    assert body["notes"][1] == "Plug and voltage data is not on file for this country yet."


def test_no_recommendations_means_no_llm_source(client, monkeypatch, trip_payload):
    use_climate(monkeypatch, ClimateInfo(summary=CLIMATE_SUMMARY, historical=True))
    use_source(monkeypatch, FakeGadgetSource(recommendations=[]))

    body = client.post("/recommend", json=trip_payload).json()

    assert body["recommendations"] == []
    assert "llm_gadget_knowledge" not in body["sources"]


def test_typed_destination_is_geocoded(client, monkeypatch, fake_source, trip_payload):
    use_climate(monkeypatch, ClimateInfo(summary=CLIMATE_SUMMARY, historical=True))
    use_source(monkeypatch, fake_source)
    monkeypatch.setenv("HOME_COUNTRY", "BD")
    looked_up = []

    async def fake_geocode(destination, home_country=None):
        looked_up.append((destination, home_country))
        return GeoResult(
            name="Sylhet", latitude=24.9, longitude=91.87,
            country="Bangladesh", country_code="BD", timezone="Asia/Dhaka",
        )

    monkeypatch.setattr("app.services.destination.aggregator.geocode", fake_geocode)
    for key in ("latitude", "longitude", "country_code", "country_name"):
        trip_payload.pop(key)

    response = client.post("/recommend", json=trip_payload)

    assert response.status_code == 200
    # Typed names are searched with the home country preferred.
    assert looked_up == [("Sylhet", "BD")]
    assert "plug_dataset" in response.json()["sources"]


def test_landmark_found_by_openstreetmap_is_credited(client, monkeypatch, fake_source, trip_payload):
    use_climate(monkeypatch, ClimateInfo(summary=CLIMATE_SUMMARY, historical=True))
    use_source(monkeypatch, fake_source)

    async def osm_hit(destination, home_country=None):
        return GeoResult(
            name="Kaptai Lake", latitude=22.76, longitude=92.276,
            country="Bangladesh", country_code="BD", timezone=None, source="openstreetmap",
        )

    monkeypatch.setattr("app.services.destination.aggregator.geocode", osm_hit)
    trip_payload.update(destination="Kaptai Lake", latitude=None, longitude=None)

    body = client.post("/recommend", json=trip_payload).json()

    assert body["sources"][0] == "openstreetmap"
    assert "open_meteo_geocoding" not in body["sources"]


def test_unknown_destination_is_404(client, monkeypatch, trip_payload):
    async def not_found(destination, home_country=None):
        return None

    monkeypatch.setattr("app.services.destination.aggregator.geocode", not_found)
    trip_payload.update(destination="Atlantis", latitude=None, longitude=None)

    response = client.post("/recommend", json=trip_payload)

    assert response.status_code == 404
    assert response.json() == {
        "detail": "Could not find a place called 'Atlantis'. "
        "Try the nearest town or district instead."
    }


def test_geocoder_outage_is_503(client, monkeypatch, trip_payload):
    async def outage(destination, home_country=None):
        raise DestinationDataException("Could not reach the geocoding service.")

    monkeypatch.setattr("app.services.destination.aggregator.geocode", outage)
    trip_payload.update(latitude=None, longitude=None)

    response = client.post("/recommend", json=trip_payload)

    assert response.status_code == 503
    assert "try again" in response.json()["detail"]


def test_llm_rate_limit_is_429(client, monkeypatch, trip_payload):
    use_climate(monkeypatch, ClimateInfo(summary=CLIMATE_SUMMARY, historical=True))
    use_source(monkeypatch, FakeGadgetSource(error=LLMRateLimitException("quota exceeded")))

    response = client.post("/recommend", json=trip_payload)

    assert response.status_code == 429
    # The provider's internal message stays in the logs.
    assert "quota" not in response.json()["detail"]


def test_llm_provider_error_is_503(client, monkeypatch, trip_payload):
    use_climate(monkeypatch, ClimateInfo(summary=CLIMATE_SUMMARY, historical=True))
    use_source(monkeypatch, FakeGadgetSource(error=LLMProviderException("gemini 500")))

    assert client.post("/recommend", json=trip_payload).status_code == 503


def test_unreadable_advisor_reply_is_503(client, monkeypatch, trip_payload):
    use_climate(monkeypatch, ClimateInfo(summary=CLIMATE_SUMMARY, historical=True))
    use_source(monkeypatch, FakeGadgetSource(error=GadgetSourceException("bad json")))

    assert client.post("/recommend", json=trip_payload).status_code == 503


def test_invalid_trip_is_422(client, trip_payload):
    trip_payload.update(start_date="2026-11-14", end_date="2026-11-10")
    assert client.post("/recommend", json=trip_payload).status_code == 422


def test_destination_search(client, monkeypatch):
    async def fake_search(query, limit, home_country=None):
        return [
            GeoResult(
                name="Sylhet", latitude=24.9, longitude=91.87,
                country="Bangladesh", country_code="BD", timezone=None,
            )
        ]

    monkeypatch.setattr("app.routes.destinations.search_destinations", fake_search)

    response = client.get("/destinations", params={"q": "syl"})

    assert response.status_code == 200
    assert response.json() == [
        {"name": "Sylhet", "country": "Bangladesh", "country_code": "BD", "latitude": 24.9, "longitude": 91.87}
    ]


def test_destination_query_too_short_is_422(client):
    assert client.get("/destinations", params={"q": "s"}).status_code == 422
