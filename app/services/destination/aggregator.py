import asyncio

from app.config import get_env_meta_info
from app.exceptions.exceptions import DestinationNotFoundException
from app.models.context import StopContext, TripContext
from app.models.trip import TripRequest
from app.services.destination.climate import fetch_climate
from app.services.destination.country import get_country_info
from app.services.destination.geocode import GeoResult, geocode


async def _resolve(name: str, latitude, longitude, country_code, country_name) -> GeoResult:
    """Where a destination is: the caller's coordinates when it has them,
    else the geocoder. Raises when the place cannot be found."""
    if latitude is not None and longitude is not None:
        # The caller already knows where this is -- from the picker, or from
        # our own curated list. No geocoder runs, so none is credited: for
        # places like Bholaganj Sada Pathor the coordinates are ours, not
        # Open-Meteo's, and claiming otherwise would be false attribution.
        return GeoResult(
            name=name,
            latitude=latitude,
            longitude=longitude,
            country=country_name,
            country_code=country_code,
            timezone=None,
            source="supplied_coordinates",
        )

    location = await geocode(name, home_country=get_env_meta_info().home_country)

    if location is None:
        raise DestinationNotFoundException(
            f"Could not find a place called '{name}'. "
            "Try the nearest town or district instead."
        )
    return location


async def _stop(trip: TripRequest, name, latitude, longitude, country_code, country_name):
    """One destination's location, climate and plugs, and the sources used."""
    location = await _resolve(name, latitude, longitude, country_code, country_name)
    sources = [location.source]

    climate = await fetch_climate(
        latitude=location.latitude,
        longitude=location.longitude,
        start_date=trip.start_date,
        end_date=trip.end_date,
    )
    if climate.available:
        sources.append("open_meteo_archive" if climate.historical else "open_meteo_forecast")

    country = get_country_info(location.country_code, location.country)
    if country.available:
        sources.append("plug_dataset")

    stop = StopContext(
        name=location.name or name,
        latitude=location.latitude,
        longitude=location.longitude,
        climate=climate,
        country=country,
    )
    return stop, sources


async def build_trip_context(trip: TripRequest) -> TripContext:
    """Assemble everything known about a trip before any gadget source runs.

    Each destination is resolved on its own -- a multi-stop trip gets every
    stop's climate and plugs -- and the stops are looked up concurrently.
    Finding the place is the one hard dependency: without a location there
    is nothing to advise on. Climate and plug data both fail soft, and only
    the sources that actually contributed are recorded.
    """
    wanted = (
        [(s.name, s.latitude, s.longitude, s.country_code, s.country_name) for s in trip.stops]
        if trip.stops
        else [(trip.destination, trip.latitude, trip.longitude, trip.country_code, trip.country_name)]
    )

    results = await asyncio.gather(*(_stop(trip, *w) for w in wanted))
    stops = [stop for stop, _ in results]
    sources = list(dict.fromkeys(src for _, srcs in results for src in srcs))
    first = stops[0]

    return TripContext(
        trip=trip,
        # One stop: its own name. Several: the whole route.
        resolved_place=first.name if len(stops) == 1 else " + ".join(s.name for s in stops),
        resolved_latitude=first.latitude,
        resolved_longitude=first.longitude,
        climate=first.climate,
        country=first.country,
        sources=sources,
        stops=stops,
    )
