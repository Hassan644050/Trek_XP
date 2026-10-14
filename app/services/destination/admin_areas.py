"""Divisions and districts for a country, loaded from static datasets.

Static rather than geocoded, for the same reason the plug data is: it
changes rarely, costs nothing per request and has no failure mode. More
importantly, global gazetteers are unreliable here -- for Bangladesh,
Open-Meteo matched the wrong place for about 11% of district names
(Kishoreganj, Rangpur, Moulvibazar and others resolved hundreds of
kilometres away), so trusting it would have silently produced wrong data.

Each country keeps its admin.json under app/data/countries/<code>/, so
these functions take a country code. A country with no data simply has no
divisions, which the callers handle as "unknown" rather than an error.
"""

import json
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

from app.services.destination.countries import get_country


@dataclass(frozen=True)
class District:
    name: str
    division: str
    latitude: float
    longitude: float


def normalize(name: str) -> str:
    """Match names ignoring case, accents and punctuation, so "Cox's Bazar",
    "coxs bazar" and "Kuakāta" all compare equal."""
    decomposed = unicodedata.normalize("NFKD", name)
    unaccented = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", unaccented.lower())


@lru_cache(maxsize=8)
def _data(country: str) -> dict:
    found = get_country(country)

    if found is None:
        return {"divisions": []}

    try:
        with found.admin_path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {"divisions": []}


@lru_cache(maxsize=8)
def districts(country: str) -> dict[str, District]:
    """A country's districts keyed by normalized name, aliases included.

    Renamed districts keep their old names as aliases: coordinators and
    older documents still say Chittagong, Comilla, Jessore and Bogra.
    """
    found: dict[str, District] = {}

    for division in _data(country).get("divisions", []):
        for entry in division.get("districts", []):
            district = District(
                name=entry["name"],
                division=division["name"],
                latitude=entry["lat"],
                longitude=entry["lon"],
            )

            for name in [entry["name"], *entry.get("also", [])]:
                found.setdefault(normalize(name), district)

    return found


@lru_cache(maxsize=8)
def divisions(country: str) -> list[str]:
    return [d["name"] for d in _data(country).get("divisions", [])]


def find_district(country: str, name: str | None) -> District | None:
    if not name:
        return None

    return districts(country).get(normalize(name))


# A point farther than this from every district centroid is treated as
# outside the country, so a trip elsewhere never snaps to one of its
# divisions. District centroids sit well under a degree apart, so any point
# inside the country is comfortably within this.
_MAX_SNAP_DEGREES = 1.0


def division_for_coords(country: str, latitude: float, longitude: float) -> str | None:
    """The division a point falls in, by nearest district centroid.

    Used to group a destination with the catalog entries around it: a
    gadget a coordinator added for the region should surface for any trip
    to that region, not only the exact spot. Returns None for a point that
    is not in the country (or a country with no data).
    """
    nearest: District | None = None
    best: float | None = None

    for district in districts(country).values():
        gap = (district.latitude - latitude) ** 2 + (district.longitude - longitude) ** 2

        if best is None or gap < best:
            best, nearest = gap, district

    if nearest is None or best > _MAX_SNAP_DEGREES**2:
        return None

    return nearest.division


def district_names(country: str, division: str | None = None) -> list[str]:
    """Unique district names, optionally limited to one division. Aliases
    are deliberately left out: they are for matching, not for display."""
    seen: dict[str, District] = {}

    for district in districts(country).values():
        if division and district.division != division:
            continue

        seen[district.name] = district

    return sorted(seen)
