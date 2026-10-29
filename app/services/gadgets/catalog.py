"""The community catalog: coordinator-entered gadgets for a destination.

This is the retrieval half of the recommend flow. The recommend route runs
it first (it is async, so it stays in the route rather than inside the
blocking gadget source), then asks the model for fresh items that avoid
whatever it finds here.

Two things come back: the gadgets worth recommending for this trip, each
marked verified, and the full set of names already on file for the place,
which the model is told to steer clear of.
"""

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload

from app.db.models import Place, Placement
from app.models.context import TripContext
from app.models.recommendation import (
    Origin,
    Priority,
    Recommendation,
    normalize_gadget_name,
)
from app.services.destination.admin_areas import division_for_coords, normalize
from app.services.destination.countries import is_supported
from app.services.media.storage import get_image_storage, variant_key
from app.services.media.variants import DETAIL


logger = logging.getLogger(__name__)

# How close a stored place must be to count as the same destination. A
# place entered by district uses the district centroid, which can sit tens
# of kilometres from the exact spot, so this is generous -- but tight
# enough to keep a same-named place in another division from matching.
# ~0.5 degrees is roughly 55 km at this latitude.
PROXIMITY_DEGREES = 0.5

_PRIORITY_RANK = {Priority.ESSENTIAL: 3, Priority.RECOMMENDED: 2, Priority.OPTIONAL: 1}


@dataclass
class CatalogMatch:
    # Verified items worth showing for this trip, most relevant first.
    recommendations: list[Recommendation] = field(default_factory=list)
    # Every gadget name on file for the place, active or retired. The model
    # must avoid all of them, so a retired item is not re-suggested either.
    existing_names: list[str] = field(default_factory=list)


async def load_catalog(db, context: TripContext) -> CatalogMatch:
    """Find the catalog gadgets for this trip's destination.

    A place matches when it is the same spot -- the same name close to the
    same point -- or when it is in the same division of the same country.
    The division rule is what makes a gadget a coordinator added for
    "Chattogram" show for a trip to Cox's Bazar: coordinators enter items
    for a region, while travellers pick specific spots within it.
    """
    name = (context.resolved_place or context.trip.destination or "").strip()
    lat, lon = context.resolved_latitude, context.resolved_longitude

    if not name and (lat is None or lon is None):
        return CatalogMatch()

    country = _trip_country(context)
    division = _trip_division(context, country)

    # Small catalogs: load the places and match in Python, which keeps the
    # name, proximity and division rules in one place. When this table grows
    # large, store each place's division on the row and filter in SQL.
    places = (await db.scalars(select(Place))).all()
    place_ids = [p.id for p in places if _place_matches(p, name, lat, lon, country, division)]

    if not place_ids:
        return CatalogMatch()

    placements = (
        await db.scalars(
            select(Placement)
            .where(Placement.place_id.in_(place_ids))
            .options(joinedload(Placement.gadget))
        )
    ).all()

    return CatalogMatch(
        recommendations=_relevant(placements, context),
        existing_names=_existing_names(placements),
    )


def _trip_country(context: TripContext) -> str:
    """The trip's country code, uppercased ("" if unknown)."""
    return (context.country.country_code or context.trip.country_code or "").upper()


def _trip_division(context: TripContext, country: str) -> str | None:
    """The division this trip falls in, or None when the country has no
    admin data (division matching then simply does not apply)."""
    lat, lon = context.resolved_latitude, context.resolved_longitude

    if lat is None or lon is None or not is_supported(country):
        return None

    return division_for_coords(country, lat, lon)


def _place_division(place: Place, country: str) -> str | None:
    """A stored place's division: its own if set, else inferred from where
    it is. Geocoded places carry no division, so most are inferred."""
    return place.division or division_for_coords(country, place.latitude, place.longitude)


def _place_matches(place, name, lat, lon, country, division) -> bool:
    # Same spot: same name, and nearby when coordinates are known.
    if name and normalize(place.name) == normalize(name):
        if (
            lat is None
            or lon is None
            or (
                abs(place.latitude - lat) <= PROXIMITY_DEGREES
                and abs(place.longitude - lon) <= PROXIMITY_DEGREES
            )
        ):
            return True

    # Same region: a coordinator's entry for the division applies here too,
    # but only within the same country -- a division name is not unique
    # across countries.
    if division is None or (place.country_code or "").upper() != country:
        return False

    return _place_division(place, country) == division


def _existing_names(placements) -> list[str]:
    """Every distinct gadget name on file, retired ones included.

    Except model suggestions still awaiting review: they are not shown to
    travellers yet, so the model must stay free to suggest them -- each
    repeat adds to their suggestion count. Rejected ones stay listed, so the
    model is steered away from them.
    """
    names: list[str] = []
    seen: set[str] = set()

    for placement in placements:
        if placement.gadget.review_status == "pending":
            continue

        key = normalize_gadget_name(placement.gadget.name)

        if key not in seen:
            seen.add(key)
            names.append(placement.gadget.name)

    return names


def _overlap(placement, wanted_activities: set[str]) -> int:
    return len(wanted_activities.intersection(placement.activities or []))


def _relevant(placements, context: TripContext) -> list[Recommendation]:
    """The catalog items worth showing for this specific trip.

    Preferred: active gadgets whose placement names one of this trip's
    types. If none
    are tagged for it, every active gadget at the place is shown rather than
    hiding the catalog over a tagging mismatch.
    """
    trip_types = set(context.trip.trip_types)
    wanted = set(context.trip.activities)

    active = [p for p in placements if p.gadget.is_active]
    for_trip = [p for p in active if trip_types.intersection(p.trip_types or [])]
    candidates = for_trip or active

    # One recommendation per gadget: if a gadget has several placements here,
    # keep the one that best fits what the traveller plans to do.
    best: dict[str, Placement] = {}

    for placement in candidates:
        key = normalize_gadget_name(placement.gadget.name)
        current = best.get(key)

        if current is None or _overlap(placement, wanted) > _overlap(current, wanted):
            best[key] = placement

    ordered = sorted(
        best.values(),
        key=lambda p: (
            -_overlap(p, wanted),
            -_PRIORITY_RANK.get(p.priority, 0),
            p.gadget.name.lower(),
        ),
    )

    return [_to_recommendation(p) for p in ordered]


def _image_url(image_key: str | None) -> str | None:
    """The card-sized rendition's URL, when the gadget has a photo."""
    if not image_key:
        return None

    return get_image_storage().url(variant_key(image_key, DETAIL.name))


def _to_recommendation(placement) -> Recommendation:
    return Recommendation(
        gadget=placement.gadget.name,
        why=placement.why,
        priority=placement.priority,
        category=placement.gadget.category,
        image_url=_image_url(placement.gadget.image_key),
        page_url=f"/gadget/{placement.gadget.slug}" if placement.gadget.slug else None,
        # A coordinator entered and vouched for this; say so.
        origin=Origin.COMMUNITY,
        verified=True,
    )


async def load_catalog_safely(db, context: TripContext) -> CatalogMatch:
    """load_catalog, but a database problem yields an empty match.

    The traveller flow must survive a catalog that is unreachable or not yet
    migrated: the recommendations simply fall back to the model alone.
    """
    try:
        return await load_catalog(db, context)
    except SQLAlchemyError:
        logger.warning("Community catalog lookup failed", exc_info=True)

        return CatalogMatch()
