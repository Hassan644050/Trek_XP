import asyncio
import re
import time

import httpx

from app.services.destination.geocode_types import GeoResult


NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
TIMEOUT_SECONDS = 10.0

# Nominatim's usage policy: identify the application, stay at or under one
# request per second, cache results, and never use it for type-ahead search.
# That last rule is why this backs only the final lookup, not the picker.
USER_AGENT = "TrekXP/0.1 (+https://github.com/Hassan644050/Trek_XP)"
MIN_INTERVAL_SECONDS = 1.0
CACHE_SIZE = 512

# Natural and visitor features only. Searching "Jaflong" also returns a
# school of that name in Dhaka, and "Dubai" a hotel -- both would send the
# traveller's weather lookup to the wrong place.
ACCEPTED_CATEGORIES = {
    "natural",
    "water",
    "waterway",
    "leisure",
    "place",
    "boundary",
    "historic",
}
ACCEPTED_TOURISM_TYPES = {"attraction", "viewpoint", "theme_park", "zoo"}

# Words that mark a query as naming a landmark rather than a town. The
# general geocoder indexes towns well and natural features poorly.
LANDMARK_WORDS = {
    "lake", "beach", "island", "islands", "valley", "waterfall", "falls",
    "forest", "park", "hill", "hills", "river", "sea", "bay", "dam",
    "reserve", "mountain", "mount", "peak", "cave", "swamp", "wetland",
    "haor", "beel", "jhorna",
}

_cache: dict[tuple[str, str | None], GeoResult | None] = {}
_lock = asyncio.Lock()
_last_request_at = 0.0


def names_a_landmark(query: str) -> bool:
    words = re.findall(r"[a-z]+", query.lower())
    return any(word in LANDMARK_WORDS for word in words)


def _is_acceptable(result: dict) -> bool:
    category = result.get("category")

    if category == "tourism":
        return result.get("type") in ACCEPTED_TOURISM_TYPES

    return category in ACCEPTED_CATEGORIES


def parse_osm_results(payload: list) -> GeoResult | None:
    """Return the first natural or visitor feature, skipping businesses.

    Pure function so the filtering can be tested against canned payloads.
    """
    for result in payload:
        if not isinstance(result, dict) or not _is_acceptable(result):
            continue

        try:
            latitude = float(result["lat"])
            longitude = float(result["lon"])
        except (KeyError, TypeError, ValueError):
            continue

        address = result.get("address") or {}
        name = result.get("name") or (result.get("display_name") or "").split(",")[0]
        country_code = address.get("country_code")

        return GeoResult(
            name=name.strip(),
            latitude=latitude,
            longitude=longitude,
            country=address.get("country"),
            country_code=country_code.upper() if country_code else None,
            timezone=None,
            source="openstreetmap",
        )

    return None


async def _fetch(params: dict) -> list:
    global _last_request_at

    async with _lock:
        wait = MIN_INTERVAL_SECONDS - (time.monotonic() - _last_request_at)

        if wait > 0:
            await asyncio.sleep(wait)

        try:
            async with httpx.AsyncClient(
                timeout=TIMEOUT_SECONDS,
                headers={"User-Agent": USER_AGENT},
            ) as client:
                response = await client.get(NOMINATIM_URL, params=params)
                response.raise_for_status()
                return response.json()
        finally:
            _last_request_at = time.monotonic()


async def osm_geocode(query: str, country_code: str | None = None) -> GeoResult | None:
    """Look a place up in OpenStreetMap, which maps landmarks well.

    Fails soft: this is a fallback behind the primary geocoder, so an
    outage here means "not found", never an error.
    """
    key = (query.strip().lower(), country_code.lower() if country_code else None)

    if key in _cache:
        return _cache[key]

    params: dict[str, object] = {
        "q": query,
        "format": "jsonv2",
        "limit": 8,
        "addressdetails": 1,
        "accept-language": "en",
    }

    if country_code:
        params["countrycodes"] = country_code.lower()

    try:
        payload = await _fetch(params)
    except (httpx.HTTPError, ValueError):
        # Not cached: the next request should try again.
        return None

    result = parse_osm_results(payload if isinstance(payload, list) else [])

    if len(_cache) >= CACHE_SIZE:
        _cache.pop(next(iter(_cache)))

    _cache[key] = result

    return result
