import asyncio
from dataclasses import dataclass

import httpx

from app.exceptions.exceptions import DestinationDataException


GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
TIMEOUT_SECONDS = 10.0


@dataclass
class GeoResult:
    name: str
    latitude: float
    longitude: float
    country: str | None
    country_code: str | None
    timezone: str | None


def parse_geocode_response(payload: dict) -> GeoResult | None:
    """Pull the first usable match out of a geocoding payload.

    Split out from the HTTP call so it can be tested against a canned
    payload without touching the network.
    """
    results = payload.get("results") or []

    if not results:
        return None

    result = results[0]
    latitude = result.get("latitude")
    longitude = result.get("longitude")

    if latitude is None or longitude is None:
        return None

    return GeoResult(
        name=result.get("name", ""),
        latitude=latitude,
        longitude=longitude,
        country=result.get("country"),
        country_code=result.get("country_code"),
        timezone=result.get("timezone"),
    )


async def geocode(destination: str) -> GeoResult | None:
    """Resolve a place name to coordinates and a country.

    Returns None when the place simply is not found -- that is a user
    error, not an outage. Raises DestinationDataException when the
    service itself is unreachable.
    """
    params = {
        "name": destination,
        "count": 1,
        "language": "en",
        "format": "json",
    }

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.get(GEOCODING_URL, params=params)
            response.raise_for_status()
            payload = response.json()

    except (httpx.HTTPError, ValueError) as exc:
        raise DestinationDataException(
            "Could not reach the geocoding service."
        ) from exc

    return parse_geocode_response(payload)


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
