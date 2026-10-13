"""Bangladesh divisions and districts, loaded from a static dataset.

Static rather than geocoded, for the same reason the plug data is: it
changes rarely, costs nothing per request and has no failure mode. More
importantly, global gazetteers are unreliable here -- Open-Meteo matched
the wrong place for about 11% of district names (Kishoreganj, Rangpur,
Moulvibazar and others resolved hundreds of kilometres away), so trusting
it would have silently produced wrong climate data.

District coordinates come from OpenStreetMap administrative boundaries,
and the division mapping is cross-checked against OSM's own labels.
"""

import json
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


ADMIN_PATH = Path(__file__).resolve().parents[2] / "data" / "bd_admin.json"

# These areas are Bangladesh-specific, so they only apply to BD places.
ADMIN_COUNTRY = "BD"


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


@lru_cache(maxsize=1)
def _data() -> dict:
    try:
        with ADMIN_PATH.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {"divisions": []}


@lru_cache(maxsize=1)
def districts() -> dict[str, District]:
    """Districts keyed by normalized name, including former spellings.

    Renamed districts keep their old names as aliases: coordinators and
    older documents still say Chittagong, Comilla, Jessore and Bogra.
    """
    found: dict[str, District] = {}

    for division in _data().get("divisions", []):
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


@lru_cache(maxsize=1)
def divisions() -> list[str]:
    return [d["name"] for d in _data().get("divisions", [])]


def find_district(name: str | None) -> District | None:
    if not name:
        return None

    return districts().get(normalize(name))


def district_names(division: str | None = None) -> list[str]:
    """Unique district names, optionally limited to one division. Aliases
    are deliberately left out: they are for matching, not for display."""
    seen: dict[str, District] = {}

    for district in districts().values():
        if division and district.division != division:
            continue

        seen[district.name] = district

    return sorted(seen)
