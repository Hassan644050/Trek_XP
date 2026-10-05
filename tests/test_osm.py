import asyncio

import httpx
import pytest

from app.services.destination import osm
from app.services.destination.osm import names_a_landmark, osm_geocode, parse_osm_results


def feature(name, category, kind, lat="22.76", lon="92.276", country_code="bd"):
    return {
        "name": name,
        "category": category,
        "type": kind,
        "lat": lat,
        "lon": lon,
        "address": {"country": "Bangladesh", "country_code": country_code},
    }


@pytest.mark.parametrize(
    "query", ["Kaptai Lake", "Kuakata Beach", "Saint Martin's Island", "Nafakhum Waterfall", "sajek valley"]
)
def test_landmark_words_are_recognised(query):
    assert names_a_landmark(query)


@pytest.mark.parametrize("query", ["Paris", "Sylhet", "Jaflong", "Parkville"])
def test_plain_place_names_are_not_landmarks(query):
    assert not names_a_landmark(query)


def test_natural_feature_is_parsed():
    result = parse_osm_results([feature("Kaptai Lake", "water", "reservoir")])
    assert (result.name, result.latitude, result.longitude) == ("Kaptai Lake", 22.76, 92.276)
    assert (result.country, result.country_code) == ("Bangladesh", "BD")
    assert result.source == "openstreetmap"


def test_businesses_are_skipped_for_the_real_place():
    # Real responses: "Jaflong" also names a school in Dhaka.
    result = parse_osm_results(
        [
            feature("Jaflong (Grameen Shikkha)", "amenity", "school", lat="23.821", lon="90.381"),
            feature("Jaflong", "place", "village", lat="25.173", lon="92.02"),
        ]
    )
    assert (result.name, result.latitude) == ("Jaflong", 25.173)


@pytest.mark.parametrize(
    ("category", "kind"),
    [("tourism", "hotel"), ("shop", "mobile_phone"), ("highway", "bus_stop"), ("amenity", "school")],
)
def test_non_places_are_rejected(category, kind):
    assert parse_osm_results([feature("Somewhere", category, kind)]) is None


def test_visitor_attractions_are_accepted():
    assert parse_osm_results([feature("Viewpoint", "tourism", "viewpoint")]) is not None


def test_entry_without_coordinates_is_skipped():
    broken = feature("Ghost Lake", "water", "lake")
    del broken["lat"]
    assert parse_osm_results([broken]) is None


def test_missing_name_falls_back_to_display_name():
    entry = feature("", "natural", "beach")
    entry["display_name"] = "Kuakata Sea Beach, Patuakhali, Bangladesh"
    assert parse_osm_results([entry]).name == "Kuakata Sea Beach"


class FakeFetch:
    def __init__(self, payload=None, error=None):
        self.payload = payload or []
        self.error = error
        self.params = []

    async def __call__(self, params):
        self.params.append(params)
        if self.error is not None:
            raise self.error
        return self.payload


def test_lookup_is_restricted_to_the_requested_country(monkeypatch):
    fetch = FakeFetch([feature("Kaptai Lake", "water", "reservoir")])
    monkeypatch.setattr(osm, "_fetch", fetch)

    result = asyncio.run(osm_geocode("Kaptai Lake", "BD"))

    assert result.name == "Kaptai Lake"
    assert fetch.params[0]["countrycodes"] == "bd"
    assert fetch.params[0]["accept-language"] == "en"


def test_repeat_lookups_are_cached(monkeypatch):
    fetch = FakeFetch([feature("Kaptai Lake", "water", "reservoir")])
    monkeypatch.setattr(osm, "_fetch", fetch)

    asyncio.run(osm_geocode("Kaptai Lake", "BD"))
    asyncio.run(osm_geocode("  kaptai lake ", "bd"))

    assert len(fetch.params) == 1


def test_misses_are_cached_too(monkeypatch):
    fetch = FakeFetch([])
    monkeypatch.setattr(osm, "_fetch", fetch)

    assert asyncio.run(osm_geocode("Bichanakandi", "BD")) is None
    assert asyncio.run(osm_geocode("Bichanakandi", "BD")) is None
    assert len(fetch.params) == 1


def test_outage_fails_soft_and_is_retried(monkeypatch):
    fetch = FakeFetch(error=httpx.ConnectError("down"))
    monkeypatch.setattr(osm, "_fetch", fetch)

    assert asyncio.run(osm_geocode("Kaptai Lake", "BD")) is None
    assert asyncio.run(osm_geocode("Kaptai Lake", "BD")) is None
    # Failures are not cached, so the service is asked again.
    assert len(fetch.params) == 2
