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

from sqlalchemy import and_, func, or_, select
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

    Matching is by name and, when coordinates are known, proximity: the
    same place label close to the same point. Coordinates alone would lump
    neighbouring destinations together; the name alone would confuse two
    places that share it.
    """
    name = (context.resolved_place or context.trip.destination or "").strip()

    if not name:
        return CatalogMatch()

    where = func.lower(Place.name) == name.lower()

    lat, lon = context.resolved_latitude, context.resolved_longitude

    if lat is not None and lon is not None:
        where = and_(
            where,
            Place.latitude.between(lat - PROXIMITY_DEGREES, lat + PROXIMITY_DEGREES),
            Place.longitude.between(lon - PROXIMITY_DEGREES, lon + PROXIMITY_DEGREES),
        )

    place_ids = (await db.scalars(select(Place.id).where(where))).all()

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


def _existing_names(placements) -> list[str]:
    """Every distinct gadget name on file, retired ones included."""
    names: list[str] = []
    seen: set[str] = set()

    for placement in placements:
        key = normalize_gadget_name(placement.gadget.name)

        if key not in seen:
            seen.add(key)
            names.append(placement.gadget.name)

    return names


def _overlap(placement, wanted_activities: set[str]) -> int:
    return len(wanted_activities.intersection(placement.activities or []))


def _relevant(placements, context: TripContext) -> list[Recommendation]:
    """The catalog items worth showing for this specific trip.

    Preferred: active gadgets whose placement names this trip type. If none
    are tagged for it, every active gadget at the place is shown rather than
    hiding the catalog over a tagging mismatch.
    """
    trip_type = context.trip.trip_type.value
    wanted = {a.value for a in context.trip.activities}

    active = [p for p in placements if p.gadget.is_active]
    for_trip = [p for p in active if trip_type in (p.trip_types or [])]
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


def _to_recommendation(placement) -> Recommendation:
    return Recommendation(
        gadget=placement.gadget.name,
        why=placement.why,
        priority=placement.priority,
        category=placement.gadget.category,
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
