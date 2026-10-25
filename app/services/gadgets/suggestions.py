"""Save the language model's new gadget suggestions to the catalog, for
coordinators to review.

When a traveller's list contains an item the catalog does not have ("Portable
Bluetooth Speaker" for Cox's Bazar), it is saved after the response has been
sent -- the traveller never waits -- as an inactive gadget with
review_status "pending", origin "model", and a placement holding the
model's reason for that destination and trip type. A coordinator approves
(it goes live, with the Verified badge) or rejects it (it stays retired, and
the model is told not to suggest it there again).

Each new gadget then gets, best effort, a short catalog description from
the model. No photo is fetched: the coordinator adds one when verifying it.

Guard rails, because the trigger is a public endpoint:
- only destinations travellers can actually pick (the curated list or an
  existing catalog place) and active trip types are saved, so made-up
  requests cannot fill the review queue with junk places;
- a suggestion that is the same item as an existing gadget by
  similarity.py ("Bluetooth Speaker" vs "Portable Bluetooth Speaker",
  "Portable Charger" vs "Power Bank") adds to that gadget's suggestion
  count instead of creating a duplicate;
- coordinator-entered and rejected gadgets are never touched.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from functools import lru_cache

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.db.models import Gadget, Place, Placement, TripTypeOption
from app.models.recommendation import Priority, Recommendation
from app.services.destination.countries import get_country
from app.services.gadgets.similarity import SAME, is_same, similarity
from app.services.slug import unique_gadget_slug
from app.services.taxonomy import active_values


logger = logging.getLogger(__name__)

PENDING, APPROVED, REJECTED = "pending", "approved", "rejected"
MODEL = "model"

DESCRIBE_TIMEOUT_SECONDS = 40


@dataclass
class SuggestionBatch:
    """What the background task needs, copied out of the request so it does
    not hold on to request objects."""

    place_name: str
    country_code: str
    trip_type: str
    suggestions: list[Recommendation] = field(default_factory=list)


# ---------- matching names ----------


def same_gadget(a: str, b: str) -> bool:
    """Whether two names are the same item -- see similarity.py."""
    return is_same(a, b)


def find_match(name: str, gadgets: list[Gadget]) -> Gadget | None:
    """The existing gadget most like this name, if it is the same item."""
    best, best_score = None, SAME
    for gadget in gadgets:
        score = similarity(name, gadget.name)
        if score >= best_score:
            best, best_score = gadget, score
    return best


# ---------- known destinations ----------


@lru_cache(maxsize=8)
def _curated(country_code: str) -> dict[str, dict]:
    """Curated destinations by lowercased name: {name, lat, lon, division}."""
    country = get_country(country_code)
    if country is None:
        return {}
    try:
        with country.destinations_path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}

    return {
        p["name"].lower(): {"name": p["name"], "lat": p["lat"], "lon": p["lon"], "division": d["name"]}
        for d in data.get("divisions", [])
        for p in d.get("places", [])
    }


async def _place_for(db, name: str, country_code: str) -> Place | None:
    """The catalog place for a destination travellers can pick, created
    from the curated list if needed; None for anything else."""
    place = await db.scalar(
        select(Place)
        .where(func.lower(Place.name) == name.lower(), Place.country_code == country_code)
        .limit(1)
    )
    if place is not None:
        return place

    curated = _curated(country_code).get(name.lower())
    if curated is None:
        return None

    country = get_country(country_code)
    place = Place(
        name=curated["name"], country_code=country_code,
        country_name=country.name if country else None,
        latitude=curated["lat"], longitude=curated["lon"], division=curated["division"],
    )
    db.add(place)
    await db.flush()
    return place


# ---------- saving ----------


def _tidy(text: str | None, limit: int) -> str | None:
    text = " ".join((text or "").split())
    return text[:limit] or None


async def save_suggestions(sessionmaker, batch: SuggestionBatch) -> list[int]:
    """Record a list's model suggestions. Returns the ids of gadgets created
    (so the caller can enrich them). Never raises."""
    if not batch.suggestions:
        return []

    try:
        async with sessionmaker() as db:
            if batch.trip_type not in await active_values(db, TripTypeOption):
                return []

            place = await _place_for(db, batch.place_name, batch.country_code)
            if place is None:
                return []

            gadgets = list(
                (await db.scalars(select(Gadget).options(selectinload(Gadget.placements)))).all()
            )
            created: list[Gadget] = []

            for rec in batch.suggestions:
                name = _tidy(rec.gadget, 120)
                if not name or not _tidy(rec.why, 300):
                    continue

                gadget = find_match(name, gadgets)

                if gadget is None:
                    gadget = Gadget(
                        name=name,
                        slug=await unique_gadget_slug(db, name),
                        category=_tidy(rec.category, 60),
                        is_active=False,
                        origin=MODEL,
                        review_status=PENDING,
                        suggestion_count=0,
                        placements=[],
                    )
                    db.add(gadget)
                    gadgets.append(gadget)
                    created.append(gadget)
                elif gadget.origin != MODEL or gadget.review_status != PENDING:
                    continue  # a coordinator's entry, or already reviewed

                gadget.suggestion_count += 1

                if not any(p.place_id == place.id for p in gadget.placements):
                    gadget.placements.append(Placement(
                        place_id=place.id,
                        trip_types=[batch.trip_type],
                        activities=[],
                        priority=rec.priority if isinstance(rec.priority, Priority) else Priority.RECOMMENDED,
                        why=_tidy(rec.why, 300),
                    ))

            await db.commit()
            return [g.id for g in created]

    except IntegrityError:
        # Another list saved the same new gadget a moment earlier; this
        # one's count is lost, which is harmless.
        logger.info("Suggestion already saved by a concurrent request")
        return []
    except Exception:
        logger.warning("Saving model suggestions failed", exc_info=True)
        return []


# ---------- enriching a new suggestion ----------


def _describe_prompt(name: str, category: str | None) -> str:
    return f"""Write a catalog entry for a travel gear website in Bangladesh.

Item: {name}
{f"Category: {category}" if category else ""}

Respond with JSON only, no markdown:
{{"description": "two plain sentences: what it is and what to look for when buying one for travel", "category": "one or two words, e.g. Power, Protection, Comfort"}}
"""


def _parse_description(raw: str) -> tuple[str | None, str | None]:
    text = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        return None, None
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        return None, None
    if not isinstance(data, dict):
        return None, None
    return _tidy(str(data.get("description") or ""), 600), _tidy(str(data.get("category") or ""), 60)


async def _describe(name: str, category: str | None) -> tuple[str | None, str | None]:
    from app.services.llm.factory import get_llm_provider

    try:
        provider = get_llm_provider()
        raw = await asyncio.wait_for(
            asyncio.to_thread(provider.generate, _describe_prompt(name, category)),
            timeout=DESCRIBE_TIMEOUT_SECONDS,
        )
    except Exception:
        logger.warning("Describing suggested gadget %r failed", name, exc_info=True)
        return None, None
    return _parse_description(raw)


async def enrich(sessionmaker, gadget_id: int) -> None:
    """Add a short catalog description (and a category, if missing) to a new
    suggestion. Best effort: skipped if the model is unavailable."""
    try:
        async with sessionmaker() as db:
            gadget = await db.get(Gadget, gadget_id)
            if gadget is None:
                return
            name, category = gadget.name, gadget.category

        description, model_category = await _describe(name, category)
        if not description and not model_category:
            return

        async with sessionmaker() as db:
            gadget = await db.get(Gadget, gadget_id)
            # A coordinator may have reviewed or edited it meanwhile: only
            # fill gaps on a still-pending suggestion.
            if gadget is None or gadget.review_status != PENDING:
                return
            if description and not gadget.description:
                gadget.description = description
            if model_category and not gadget.category:
                gadget.category = model_category
            await db.commit()
    except Exception:
        logger.warning("Enriching suggested gadget %s failed", gadget_id, exc_info=True)


async def record_and_enrich(sessionmaker, batch: SuggestionBatch) -> None:
    """The background task the /recommend route schedules."""
    for gadget_id in await save_suggestions(sessionmaker, batch):
        await enrich(sessionmaker, gadget_id)
