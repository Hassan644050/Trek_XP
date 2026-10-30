"""Remember the model's fresh suggestions per kind of trip.

A packing list waited 12-30 seconds on the model, sometimes over a minute,
and the free tier allows only ~20 calls a day -- yet travellers mostly plan
the same few trips. So the model's items for a trip are stored, and the
next traveller planning the same trip gets them at once, for no model call.

The key is what shapes the model's answer, normalised so near-identical
trips share it:
- the places (sorted, so a route's order does not matter for what to pack);
- the month of travel -- the climate is last year's for those dates, so it
  is seasonal; exact dates are not part of the key;
- trip types, activities, baggage and who is travelling;
- trip length and party size in buckets ("4-7 days", "2-4 people");
- how many items were asked for, and PROMPT_VERSION.

Only the model's items are cached. Weather, plugs and the verified catalog
are always fresh, and the cached items are filtered against today's catalog
on the way out (an item a coordinator has since added is not repeated).

Fails soft both ways: a cache that cannot be read is a miss, one that cannot
be written is skipped. Neither ever fails or slows a traveller's list.
"""

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert

from app.db.engine import get_sessionmaker
from app.db.models import ModelListCache
from app.models.context import TripContext
from app.models.recommendation import Recommendation


logger = logging.getLogger(__name__)

# Bump when the prompt or the reply format changes, so old answers are not
# served for a question that is now asked differently.
PROMPT_VERSION = 2
# Long enough to cover a season of repeat trips; short enough that the
# model's knowledge (and our prompt) catch up.
MAX_AGE = timedelta(days=30)


def _days_bucket(days: int) -> str:
    if days <= 3:
        return "1-3"
    if days <= 7:
        return "4-7"
    if days <= 14:
        return "8-14"
    return "15+"


def _party_bucket(travelers: int) -> str:
    if travelers == 1:
        return "1"
    if travelers <= 4:
        return "2-4"
    return "5+"


def cache_key(context: TripContext) -> str:
    trip = context.trip
    places = [s.name for s in context.stops] or [context.resolved_place or trip.destination or ""]
    shape = {
        "v": PROMPT_VERSION,
        "country": (trip.country_code or context.country.country_code or "").upper(),
        "places": sorted(p.strip().lower() for p in places),
        "month": trip.start_date.month,
        "trip_types": sorted(trip.trip_types),
        "activities": sorted(trip.activities),
        "baggage": trip.baggage.value if trip.baggage else None,
        "gender": trip.gender,
        "days": _days_bucket(trip.duration_days),
        "party": _party_bucket(trip.travelers),
        "count": context.novel_item_count,
    }
    return hashlib.sha256(json.dumps(shape, sort_keys=True).encode()).hexdigest()


async def get_items(key: str, *, count_hit: bool = True) -> list[Recommendation] | None:
    """The cached items for this trip, or None on a miss (or any problem).
    `count_hit` is off for the home page's quick preview of the same list."""
    now = datetime.now(timezone.utc)
    try:
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as db:
            # Read and count the hit in one statement: each round trip to
            # the database costs real time on the traveller's wait.
            items = await db.scalar(
                update(ModelListCache)
                .where(ModelListCache.key == key, ModelListCache.created_at > now - MAX_AGE)
                .values(
                    hit_count=ModelListCache.hit_count + (1 if count_hit else 0),
                    last_hit_at=now,
                )
                .returning(ModelListCache.items)
            )
            await db.commit()
            if not items:
                return None
            return [Recommendation.model_validate(item) for item in items]
    except Exception:
        logger.warning("Reading the list cache failed; asking the model", exc_info=True)
        return None


async def put_items(key: str, items: list[Recommendation]) -> None:
    """Store (or refresh) the model's items for this trip. Never raises."""
    if not items:
        return
    payload = [item.model_dump(mode="json") for item in items]
    try:
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as db:
            await db.execute(
                insert(ModelListCache)
                .values(key=key, items=payload, hit_count=0)
                .on_conflict_do_update(
                    index_elements=[ModelListCache.key],
                    set_={"items": payload, "created_at": datetime.now(timezone.utc), "hit_count": 0},
                )
            )
            await db.commit()
    except Exception:
        logger.warning("Saving to the list cache failed", exc_info=True)
