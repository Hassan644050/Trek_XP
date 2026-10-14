import json
import logging
from collections import OrderedDict
from functools import lru_cache

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_env_meta_info
from app.db.engine import get_sessionmaker
from app.db.models import Gadget, Place, Placement
from app.exceptions.exceptions import DatabaseNotConfiguredException
from app.services.destination.admin_areas import division_for_coords, normalize
from app.services.destination.countries import get_country, home_country
from app.services.destination.geocode import search_destinations


logger = logging.getLogger(__name__)

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
def _curated(country_code: str) -> list[FeaturedDivision]:
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


async def _catalog_places(country_code: str) -> list[Place]:
    """Catalog places in this country that have at least one active gadget.

    So a destination a coordinator enters and stocks becomes selectable on
    the home page, not only matchable behind the scenes. Best effort: with
    no database the picker falls back to the curated list alone.
    """
    try:
        sessionmaker = get_sessionmaker()
    except DatabaseNotConfiguredException:
        return []

    stocked = (
        select(Placement.place_id)
        .join(Gadget, Gadget.id == Placement.gadget_id)
        .where(Gadget.is_active.is_(True))
    )

    try:
        async with sessionmaker() as db:
            return list(
                (
                    await db.scalars(
                        select(Place).where(
                            Place.country_code == country_code,
                            Place.id.in_(stocked),
                        )
                    )
                ).all()
            )
    except SQLAlchemyError:
        logger.warning("Featured catalog-place lookup failed", exc_info=True)
        return []


def _merge(curated: list[FeaturedDivision], places: list[Place], country_code: str) -> list[FeaturedDivision]:
    """Curated destinations first, with stocked catalog places added to
    their division. A catalog place already curated is left to the curated
    entry, which keeps its anchored coordinates and the home-page default."""
    groups: OrderedDict[str, list[FeaturedPlace]] = OrderedDict()
    seen: set[tuple[str, str]] = set()
    country = get_country(country_code)

    for division in curated:
        groups[division.name] = list(division.places)
        for place in division.places:
            seen.add((division.name, normalize(place.name)))

    for place in places:
        division = place.division or division_for_coords(
            country_code, place.latitude, place.longitude
        )

        # No division means we cannot file it under a dropdown heading.
        if not division:
            continue

        key = (division, normalize(place.name))
        if key in seen:
            continue
        seen.add(key)

        groups.setdefault(division, []).append(
            FeaturedPlace(
                name=place.name,
                latitude=place.latitude,
                longitude=place.longitude,
                country_code=country.code if country else (place.country_code or country_code),
                country_name=country.name if country else (place.country_name or ""),
            )
        )

    return [FeaturedDivision(name=name, places=places_) for name, places_ in groups.items()]


@router.get("/destinations/featured", response_model=list[FeaturedDivision])
async def featured(
    country: str | None = Query(default=None, min_length=2, max_length=2),
) -> list[FeaturedDivision]:
    """Destinations grouped by division, for the picker.

    Curated showcase spots plus any catalog destination a coordinator has
    stocked. Defaults to the configured home country; `?country=` selects
    another once its data is in place.
    """
    code = (country or home_country().code).upper()

    return _merge(_curated(code), await _catalog_places(code), code)
