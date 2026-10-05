import asyncio
import re
import unicodedata

import httpx

from app.exceptions.exceptions import DestinationDataException
from app.services.destination.geocode_types import GeoResult
from app.services.destination.osm import names_a_landmark, osm_geocode


GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
TIMEOUT_SECONDS = 10.0

__all__ = ["GeoResult", "geocode", "search_destinations"]


def _normalized(name: str) -> str:
    """Compare names ignoring case, accents and punctuation: "Kuakāta" and
    "kuakata" are the same place name, "Cox's Bazar" and "Coxs Bazar" too."""
    decomposed = unicodedata.normalize("NFKD", name)
    unaccented = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", unaccented.lower())


def _same_name(query: str, place: GeoResult) -> bool:
    return _normalized(query) == _normalized(place.name)


async def geocode(
    destination: str,
    home_country: str | None = None,
) -> GeoResult | None:
    """Resolve a typed place name to coordinates and a country.

    Open-Meteo indexes towns well but natural landmarks poorly: "Kaptai
    Lake", "Jaflong" and "Sundarbans" are missing, and "Saint Martin's
    Island" matches an island in the United States. OpenStreetMap fills
    those gaps, consulted in this order:

    1. Open-Meteo, home country -- exact name only. Its search is fuzzy, so
       an unfiltered home match turns "Paris" into the village Parisura.
    2. OpenStreetMap, home country -- only if the name contains a landmark
       word, so a foreign Open-Meteo match cannot win over a local landmark.
    3. Open-Meteo, worldwide. Plain names like "Paris" stop here.
    4. OpenStreetMap, home country, then worldwide.

    Returns None when nothing matches -- a user error, not an outage.
    Raises DestinationDataException only when Open-Meteo is unreachable.
    """
    landmark = names_a_landmark(destination)

    if home_country:
        local = await _search(destination, 5, country_code=home_country)
        exact = next((place for place in local if _same_name(destination, place)), None)

        if exact:
            return exact

        if landmark:
            found = await osm_geocode(destination, home_country)

            if found:
                return found

    worldwide = await _search(destination, 1)

    if worldwide:
        return worldwide[0]

    if home_country and not landmark:
        found = await osm_geocode(destination, home_country)

        if found:
            return found

    return await osm_geocode(destination)


async def _search(
    query: str,
    limit: int,
    country_code: str | None = None,
) -> list[GeoResult]:
    params: dict[str, object] = {
        "name": query,
        "count": limit,
        "language": "en",
        "format": "json",
    }

    if country_code:
        params["countryCode"] = country_code

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.get(GEOCODING_URL, params=params)
            response.raise_for_status()
            payload = response.json()

    except (httpx.HTTPError, ValueError) as exc:
        raise DestinationDataException(
            "Could not reach the geocoding service."
        ) from exc

    return parse_geocode_results(payload)


async def search_destinations(
    query: str,
    limit: int = 5,
    home_country: str | None = None,
) -> list[GeoResult]:
    """Return candidate places for a partial query, home country first.

    The global index buries local places behind better-known foreign
    namesakes: "cox" returns Cox in Spain, France and the United States
    while Cox's Bazar -- Bangladesh's largest beach destination -- never
    appears. Querying the home country separately and listing those matches
    first fixes that without restricting anyone to domestic travel.

    The two lookups are independent, so they go out together.
    """
    if not home_country:
        return await _search(query, limit)

    local, worldwide = await asyncio.gather(
        _search(query, limit, country_code=home_country),
        _search(query, limit),
    )

    merged: list[GeoResult] = []
    seen: set[tuple[str, float, float]] = set()

    for place in [*local, *worldwide]:
        key = (place.name, round(place.latitude, 3), round(place.longitude, 3))

        if key in seen:
            continue

        seen.add(key)
        merged.append(place)

    return merged[:limit]


def parse_geocode_results(payload: dict) -> list[GeoResult]:
    places: list[GeoResult] = []

    for result in payload.get("results") or []:
        latitude = result.get("latitude")
        longitude = result.get("longitude")

        if latitude is None or longitude is None:
            continue

        places.append(
            GeoResult(
                name=result.get("name", ""),
                latitude=latitude,
                longitude=longitude,
                country=result.get("country"),
                country_code=result.get("country_code"),
                timezone=result.get("timezone"),
            )
        )

    return places
