from app.exceptions.exceptions import DestinationNotFoundException
from app.models.context import TripContext
from app.models.trip import TripRequest
from app.services.destination.climate import fetch_climate
from app.services.destination.country import get_country_info
from app.services.destination.geocode import geocode


async def build_trip_context(trip: TripRequest) -> TripContext:
    """Assemble everything known about a trip before any gadget source runs.

    Geocoding is the one hard dependency: without a location there is
    nothing to advise on. Climate and plug data both fail soft, and only
    the sources that actually contributed are recorded.

    The two network calls are sequential by necessity -- the climate
    lookup needs coordinates the geocoder has not returned yet -- so there
    is nothing here to run concurrently until more sources are added.
    """
    location = await geocode(trip.destination)

    if location is None:
        raise DestinationNotFoundException(
            f"Could not find a place called '{trip.destination}'."
        )

    sources = ["open_meteo_geocoding"]

    climate = await fetch_climate(
        latitude=location.latitude,
        longitude=location.longitude,
        start_date=trip.start_date,
        end_date=trip.end_date,
    )

    if climate.available:
        sources.append(
            "open_meteo_archive" if climate.historical else "open_meteo_forecast"
        )

    country = get_country_info(location.country_code, location.country)

    if country.available:
        sources.append("plug_dataset")

    return TripContext(
        trip=trip,
        resolved_place=location.name or None,
        climate=climate,
        country=country,
        sources=sources,
    )
