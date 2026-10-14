import json
from functools import lru_cache

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.config import get_env_meta_info
from app.services.destination.countries import get_country, home_country
from app.services.destination.geocode import search_destinations


router = APIRouter()


class DestinationMatch(BaseModel):
    name: str
    country: str | None = None
    country_code: str | None = None
    latitude: float
    longitude: float


@router.get("/destinations", response_model=list[DestinationMatch])
async def destinations(
    q: str = Query(min_length=2, max_length=100),
    limit: int = Query(default=5, ge=1, le=10),
) -> list[DestinationMatch]:
    """Search places for the destination picker."""
    matches = await search_destinations(
        q, limit, home_country=get_env_meta_info().home_country
    )

    return [
        DestinationMatch(
            name=match.name,
            country=match.country,
            country_code=match.country_code,
            latitude=match.latitude,
            longitude=match.longitude,
        )
        for match in matches
    ]


class FeaturedPlace(BaseModel):
    name: str
    latitude: float
    longitude: float
    # Carried through to /recommend: without it the plug and voltage
    # lookup has no country to work from.
    country_code: str = "BD"
    country_name: str = "Bangladesh"
    # The one place the home page starts on, so a first-time visitor sees
    # a finished form instead of an empty one. Set in the dataset rather
    # than matched by name in the page, which would break on a rename.
    is_default: bool = False


class FeaturedDivision(BaseModel):
    name: str
    places: list[FeaturedPlace]


@lru_cache(maxsize=8)
def _featured(country_code: str) -> list[FeaturedDivision]:
    """Hand-checked destinations for one country, grouped by division.

    Static, and deliberately not geocoded at runtime: for Bangladesh three
    of these resolve to the wrong place entirely (Nilgiri matched the
    Nilgiri Hills in India, 1,588km away), and two are on no map at all.
    """
    country = get_country(country_code)

    if country is None:
        return []

    try:
        with country.destinations_path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return []

    return [
        FeaturedDivision(
            name=division["name"],
            places=[
                FeaturedPlace(
                    name=p["name"],
                    latitude=p["lat"],
                    longitude=p["lon"],
                    country_code=country.code,
                    country_name=country.name,
                    is_default=bool(p.get("default")),
                )
                for p in division["places"]
            ],
        )
        for division in data.get("divisions", [])
    ]


@router.get("/destinations/featured", response_model=list[FeaturedDivision])
async def featured(
    country: str | None = Query(default=None, min_length=2, max_length=2),
) -> list[FeaturedDivision]:
    """Popular destinations, grouped by division, for the picker.

    Defaults to the configured home country; `?country=` selects another
    one once its data is in place.
    """
    code = (country or home_country().code).upper()

    return _featured(code)
