import asyncio

from app.services.destination import geocode as geocode_module
from app.services.destination.geocode import (
    GeoResult,
    geocode,
    parse_geocode_results,
    search_destinations,
)


def place(name, lat, lon, code):
    return GeoResult(
        name=name, latitude=lat, longitude=lon, country=None, country_code=code, timezone=None
    )


class Lookups:
    """Canned answers for both geocoders, recording every call made."""

    def __init__(self, open_meteo=None, osm=None):
        self.open_meteo = open_meteo or {}
        self.osm = osm or {}
        self.calls = []

    def install(self, monkeypatch):
        async def fake_search(query, limit, country_code=None):
            self.calls.append(("open_meteo", country_code))
            hit = self.open_meteo.get(country_code)
            return [hit] if hit else []

        async def fake_osm(query, country_code=None):
            self.calls.append(("osm", country_code))
            return self.osm.get(country_code)

        monkeypatch.setattr(geocode_module, "_search", fake_search)
        monkeypatch.setattr(geocode_module, "osm_geocode", fake_osm)


SYLHET = place("Sylhet", 24.9, 91.87, "BD")
ST_MARTIN_US = place("Saint Martin Islands", 30.0, -89.0, "US")
ST_MARTIN_BD = place("St. Martin's Island", 20.611, 92.327, "BD")
PARIS = place("Paris", 48.85, 2.35, "FR")
JAFLONG = place("Jaflong", 25.173, 92.02, "BD")


def test_home_country_town_is_found_first(monkeypatch):
    lookups = Lookups(open_meteo={"BD": SYLHET})
    lookups.install(monkeypatch)

    assert asyncio.run(geocode("Sylhet", home_country="BD")) is SYLHET
    assert lookups.calls == [("open_meteo", "BD")]


def test_fuzzy_home_match_does_not_hijack_a_foreign_city(monkeypatch):
    # Real Open-Meteo behaviour: "Paris" restricted to Bangladesh returns Parisura.
    lookups = Lookups(open_meteo={"BD": place("Parisura", 23.996, 90.005, "BD"), None: PARIS})
    lookups.install(monkeypatch)

    assert asyncio.run(geocode("Paris", home_country="BD")) is PARIS


def test_home_match_ignores_accents_and_punctuation(monkeypatch):
    kuakata = place("Kuakāta", 21.82, 90.12, "BD")
    lookups = Lookups(open_meteo={"BD": kuakata})
    lookups.install(monkeypatch)

    assert asyncio.run(geocode("kuakata", home_country="BD")) is kuakata


def test_local_landmark_beats_foreign_namesake(monkeypatch):
    lookups = Lookups(open_meteo={None: ST_MARTIN_US}, osm={"BD": ST_MARTIN_BD})
    lookups.install(monkeypatch)

    assert asyncio.run(geocode("Saint Martin's Island", home_country="BD")) is ST_MARTIN_BD
    assert ("open_meteo", None) not in lookups.calls


def test_plain_foreign_name_never_asks_openstreetmap(monkeypatch):
    lookups = Lookups(open_meteo={None: PARIS}, osm={"BD": place("Paris Rd", 23.0, 90.0, "BD")})
    lookups.install(monkeypatch)

    assert asyncio.run(geocode("Paris", home_country="BD")) is PARIS
    assert lookups.calls == [("open_meteo", "BD"), ("open_meteo", None)]


def test_place_missing_from_open_meteo_falls_back_to_openstreetmap(monkeypatch):
    lookups = Lookups(osm={"BD": JAFLONG})
    lookups.install(monkeypatch)

    assert asyncio.run(geocode("Jaflong", home_country="BD")) is JAFLONG
    assert lookups.calls == [("open_meteo", "BD"), ("open_meteo", None), ("osm", "BD")]


def test_foreign_landmark_found_worldwide(monkeypatch):
    bled = place("Lake Bled", 46.36, 14.09, "SI")
    lookups = Lookups(osm={None: bled})
    lookups.install(monkeypatch)

    assert asyncio.run(geocode("Lake Bled", home_country="BD")) is bled
    assert lookups.calls[-1] == ("osm", None)


def test_nothing_anywhere_is_none(monkeypatch):
    Lookups().install(monkeypatch)
    assert asyncio.run(geocode("Atlantis", home_country="BD")) is None


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
