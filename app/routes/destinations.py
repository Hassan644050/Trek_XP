import asyncio
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
from app.db.models import ActivityOption, Place, TripTypeOption
from app.exceptions.exceptions import DatabaseNotConfiguredException
from app.models.catalog import HeroImageOut, Option
from app.services.destination.admin_areas import division_for_coords, normalize
from app.services.destination.countries import get_country, home_country, is_supported
from app.services.destination.geocode import search_destinations
from app.services.heroes import hero_out, list_heroes
from app.services.read_cache import ReadCache
from app.services.taxonomy import SEED_ACTIVITIES, SEED_TRIP_TYPES, list_options


logger = logging.getLogger(__name__)

router = APIRouter()

# Public, read-mostly lookups every home page view makes; see read_cache.py.
_options_cache = ReadCache("form options")
_featured_cache = ReadCache("featured destinations")
_hero_cache = ReadCache("hero images")


class FormOptions(BaseModel):
    trip_types: list[Option]
    activities: list[Option]


def _seed_options() -> FormOptions:
    return FormOptions(
        trip_types=[Option(value=v, label=label) for v, label in SEED_TRIP_TYPES],
        activities=[Option(value=v, label=label) for v, label in SEED_ACTIVITIES],
    )


async def _load_options() -> FormOptions:
    async with get_sessionmaker()() as db:
        trip_types = await list_options(db, TripTypeOption, active_only=True)
        activities = await list_options(db, ActivityOption, active_only=True)

    if not trip_types or not activities:
        return _seed_options()

    return FormOptions(
        trip_types=[Option(value=o.value, label=o.label) for o in trip_types],
        activities=[Option(value=o.value, label=o.label) for o in activities],
    )


@router.get("/options", response_model=FormOptions)
async def form_options() -> FormOptions:
    """Trip types and activities for the traveller form.

    Best effort: if the database is unreachable the form still works off the
    seed values, so a taxonomy outage never leaves the picker empty.
    """
    try:
        return await _options_cache.get("all", _load_options)
    except DatabaseNotConfiguredException:
        return _seed_options()
    except SQLAlchemyError:
        logger.warning("Form options lookup failed; using seed values", exc_info=True)
        return _seed_options()


@router.get("/heroes", response_model=list[HeroImageOut])
async def hero_images(
    country: str | None = Query(default=None, min_length=2, max_length=2),
) -> list[HeroImageOut]:
    """Hero photos for the home page: the country's default (place_slug "")
    and any per-destination ones, which the page swaps in as the traveller
    picks a place.

    Best effort, like /options: without the database the hero keeps its
    plain gradient, so an outage costs a photo, never the page.
    """
    code = (country or home_country().code).upper()

    # Only countries we serve: otherwise every made-up code would cost a
    # database query and leave an entry in the cache.
    if not is_supported(code):
        return []

    async def load() -> list[HeroImageOut]:
        async with get_sessionmaker()() as db:
            return [hero_out(h) for h in await list_heroes(db, code)]

    try:
        return await _hero_cache.get(code, load)
    except DatabaseNotConfiguredException:
        return []
    except SQLAlchemyError:
        logger.warning("Hero image lookup failed; showing none", exc_info=True)
        return []


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
    """Every destination on file in this country -- whether or not it has
    gadgets yet.

    A place an admin or coordinator adds is selectable on the home page
    straight away: for a place with no verified gadgets the model suggests
    the whole list, and its new items go to the coordinators' review queue,
    so the place fills in over time. Places that cannot be filed under a
    division are left out by _merge. Raises when the database is missing or
    unreachable; `featured` then falls back to the curated list alone.
    """
    async with get_sessionmaker()() as db:
        return list(
            (
                await db.scalars(
                    select(Place)
                    .where(Place.country_code == country_code)
                    .order_by(Place.name)
                )
            ).all()
        )


def _merge(curated: list[FeaturedDivision], places: list[Place], country_code: str) -> list[FeaturedDivision]:
    """Curated destinations first, with the other catalog places added to
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

    Curated showcase spots plus every other destination on file, with or
    without gadgets -- the model suggests gear for any of them. Defaults to the configured home country; `?country=` selects
    another once its data is in place.
    """
    code = (country or home_country().code).upper()

    async def load() -> list[FeaturedDivision]:
        return _merge(_curated(code), await _catalog_places(code), code)

    try:
        return await _featured_cache.get(code, load)
    except DatabaseNotConfiguredException:
        return _merge(_curated(code), [], code)
    except SQLAlchemyError:
        logger.warning("Featured catalog-place lookup failed", exc_info=True)
        return _merge(_curated(code), [], code)


async def warm_public_caches() -> None:
    """Fill the home page caches at startup, so the first visitor after a
    deploy or restart does not wait on the database either. Best effort:
    each route already falls back on its own when the database is down."""
    try:
        await asyncio.gather(
            form_options(),
            featured(country=None),
            hero_images(country=None),
        )
    except Exception:
        logger.warning("Warming the public caches failed", exc_info=True)
