import json
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.config import get_env_meta_info
from app.services.destination.geocode import search_destinations


FEATURED_PATH = Path(__file__).resolve().parents[1] / "data" / "bd_destinations.json"


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


@lru_cache(maxsize=1)
def _featured() -> list[FeaturedDivision]:
    """Hand-checked destinations for the home market.

    Static, and deliberately not geocoded at runtime: three of these
    resolve to the wrong place entirely (Nilgiri matched the Nilgiri Hills
    in India, 1,588km away), and two are on no map at all.
    """
    try:
        with FEATURED_PATH.open(encoding="utf-8") as handle:
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
                    is_default=bool(p.get("default")),
                )
                for p in division["places"]
            ],
        )
        for division in data.get("divisions", [])
    ]


@router.get("/destinations/featured", response_model=list[FeaturedDivision])
async def featured() -> list[FeaturedDivision]:
    """Popular destinations, grouped by division, for the picker."""
    return _featured()
