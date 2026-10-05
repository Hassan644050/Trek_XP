import asyncio

from app.services.destination import geocode as geocode_module
from app.services.destination.geocode import (
    GeoResult,
    parse_geocode_response,
    parse_geocode_results,
    search_destinations,
)


def place(name, lat, lon, code):
    return GeoResult(
        name=name, latitude=lat, longitude=lon, country=None, country_code=code, timezone=None
    )


def test_empty_payload_means_not_found():
    assert parse_geocode_response({}) is None
    assert parse_geocode_response({"results": []}) is None


def test_first_match_is_used():
    result = parse_geocode_response(
        {
            "results": [
                {"name": "Sylhet", "latitude": 24.9, "longitude": 91.87, "country": "Bangladesh", "country_code": "BD"},
                {"name": "Sylhet Lines", "latitude": 24.94, "longitude": 67.22, "country_code": "PK"},
            ]
        }
    )
    assert (result.name, result.country_code) == ("Sylhet", "BD")


def test_match_without_coordinates_is_unusable():
    assert parse_geocode_response({"results": [{"name": "Ghost"}]}) is None


def test_result_list_skips_entries_without_coordinates():
    results = parse_geocode_results(
        {"results": [{"name": "Ghost"}, {"name": "Real", "latitude": 1.0, "longitude": 2.0}]}
    )
    assert [r.name for r in results] == ["Real"]


def test_home_country_matches_come_first_and_duplicates_merge(monkeypatch):
    coxs_bazar = place("Cox's Bazar", 21.4272, 92.0058, "BD")
    calls = []

    async def fake_search(query, limit, country_code=None):
        calls.append(country_code)
        if country_code == "BD":
            return [coxs_bazar]
        # The worldwide index buries the local place and repeats it.
        return [place("Cox", 40.0, -3.0, "ES"), coxs_bazar, place("Cox", 45.0, 1.0, "FR")]

    monkeypatch.setattr(geocode_module, "_search", fake_search)

    results = asyncio.run(search_destinations("cox", limit=3, home_country="BD"))

    assert sorted(calls, key=str) == sorted(["BD", None], key=str)
    assert [(r.name, r.country_code) for r in results] == [
        ("Cox's Bazar", "BD"),
        ("Cox", "ES"),
        ("Cox", "FR"),
    ]


def test_no_home_country_searches_once(monkeypatch):
    calls = []

    async def fake_search(query, limit, country_code=None):
        calls.append(country_code)
        return [place("Paris", 48.85, 2.35, "FR")]

    monkeypatch.setattr(geocode_module, "_search", fake_search)

    results = asyncio.run(search_destinations("paris", limit=5))

    assert calls == [None]
    assert [r.name for r in results] == ["Paris"]
