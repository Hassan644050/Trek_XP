import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks

from app.config import get_env_meta_info
from app.db.engine import get_sessionmaker
from app.exceptions.exceptions import (
    DatabaseNotConfiguredException,
    GadgetSourceException,
    LLMException,
    LLMTimeoutException,
)
from app.models.context import TripContext
from app.models.recommendation import RecommendResponse, StopSummary
from app.models.trip import TripRequest
from app.services import analytics
from app.services.destination.aggregator import build_trip_context
from app.services.gadgets.catalog import CatalogMatch, load_catalog_safely
from app.services.gadgets.factory import get_gadget_source
from app.services.gadgets.similarity import is_same
from app.services.gadgets.suggestions import SuggestionBatch, record_and_enrich


logger = logging.getLogger(__name__)

router = APIRouter()

LLM_SOURCE_NAME = "llm_gadget_knowledge"
CATALOG_SOURCE_NAME = "community_catalog"

# How many fresh items to ask the model for, on top of the catalog: five,
# and two more for each extra stop of a multi-stop trip (at most nine).
NOVEL_ITEMS = 5
NOVEL_PER_EXTRA_STOP = 2
NOVEL_MAX = 9


def _novel_count(context: TripContext) -> int:
    extra = max(len(context.stops) - 1, 0)
    return min(NOVEL_ITEMS + NOVEL_PER_EXTRA_STOP * extra, NOVEL_MAX)


def _context_notes(context: TripContext) -> list[str]:
    if len(context.stops) > 1:
        return _route_notes(context)
    return _single_notes(context)


def _route_notes(context: TripContext) -> list[str]:
    """Per-stop weather and per-country plugs for a multi-stop trip."""
    notes: list[str] = []
    for stop in context.stops:
        notes.append(
            f"{stop.name}: {stop.climate.summary}" if stop.climate.available and stop.climate.summary
            else f"{stop.name}: climate data was unavailable for these dates."
        )
    seen = set()
    for stop in context.stops:
        c = stop.country
        key = c.country_code or c.country_name
        if key in seen:
            continue
        seen.add(key)
        notes.append(
            f"{c.country_name}: plug type {'/'.join(c.plug_types) or 'unknown'}, {c.voltage} {c.frequency}."
            if c.available else f"Plug and voltage data is not on file for {c.country_name or stop.name} yet."
        )
    return notes


def _single_notes(context: TripContext) -> list[str]:
    """What the destination facts were -- or weren't.

    Absences are stated explicitly: a traveller should know when weather or
    plug data was missing rather than assume it was considered.
    """
    notes: list[str] = []

    if context.climate.available and context.climate.summary:
        notes.append(context.climate.summary)
    else:
        notes.append(
            "Climate data was unavailable for these dates; "
            "recommendations do not account for weather."
        )

    country = context.country

    if country.available:
        plugs = "/".join(country.plug_types) or "unknown"
        notes.append(
            f"{country.country_name}: plug type {plugs}, "
            f"{country.voltage} {country.frequency}."
        )
    else:
        notes.append(
            "Plug and voltage data is not on file for this country yet."
        )

    return notes


def _provenance_notes(
    context: TripContext,
    catalog: CatalogMatch,
    novel: list,
    live_unavailable: bool,
) -> list[str]:
    """Tell the traveller which items are vouched for and which are fresh."""
    notes: list[str] = []
    place = context.resolved_place or context.trip.destination
    verified = len(catalog.recommendations)

    if verified:
        notes.append(
            f"{verified} item{'s' if verified != 1 else ''} "
            f"community-verified for {place} by a coordinator."
        )

    if live_unavailable:
        notes.append(
            "Fresh suggestions are unavailable right now; "
            "showing community-verified items only."
        )
    elif novel:
        notes.append(
            f"{len(novel)} further suggestion{'s' if len(novel) != 1 else ''} "
            "come from a language model and are not yet community-verified."
        )

    return notes


async def _load_catalog(context: TripContext) -> CatalogMatch:
    """The catalog for this destination, or empty if there is no database.

    A missing or unreachable database must not fail the traveller: the flow
    simply falls back to model suggestions alone.
    """
    try:
        sessionmaker = get_sessionmaker()
    except DatabaseNotConfiguredException:
        return CatalogMatch()

    async with sessionmaker() as db:
        if len(context.stops) <= 1:
            return await load_catalog_safely(db, context)

        # A route: each stop's verified items, then merged.
        matches = []
        for stop in context.stops:
            sub = context.model_copy(update={
                "resolved_place": stop.name,
                "resolved_latitude": stop.latitude,
                "resolved_longitude": stop.longitude,
                "climate": stop.climate,
                "country": stop.country,
                "stops": [stop],
            })
            matches.append((stop.name, await load_catalog_safely(db, sub)))
        return _merge_route_catalog(matches)


def _merge_route_catalog(matches: list[tuple[str, CatalogMatch]]) -> CatalogMatch:
    """Merge each stop's catalog match. An item found at several stops
    appears once, tagged with those stops; found at every stop, it is for
    the whole trip (no tag). Names are compared by similarity."""
    merged = CatalogMatch()
    for name, match in matches:
        for rec in match.recommendations:
            twin = next((r for r in merged.recommendations if is_same(r.gadget, rec.gadget)), None)
            if twin is None:
                merged.recommendations.append(rec.model_copy(update={"stops": [name]}))
            elif name not in twin.stops:
                twin.stops.append(name)
        for existing in match.existing_names:
            if not any(is_same(existing, n) for n in merged.existing_names):
                merged.existing_names.append(existing)

    every = {name for name, _ in matches}
    for rec in merged.recommendations:
        if set(rec.stops) == every:
            rec.stops = []
    return merged


def _schedule_suggestions(background: BackgroundTasks, context: TripContext, novel: list) -> None:
    """Save the model's new items for coordinator review, after the response
    has gone out -- see services/gadgets/suggestions.py."""
    if not novel:
        return

    try:
        sessionmaker = get_sessionmaker()
    except DatabaseNotConfiguredException:
        return

    batch = SuggestionBatch(
        place_name=context.stops[0].name if context.stops else (context.resolved_place or context.trip.destination),
        place_names=[s.name for s in context.stops],
        country_code=(context.trip.country_code or context.country.country_code or "").upper(),
        trip_type=context.trip.trip_type,
        suggestions=list(novel),
    )
    background.add_task(record_and_enrich, sessionmaker, batch)


@router.post("/recommend", response_model=RecommendResponse)
async def recommend(request: TripRequest, background: BackgroundTasks) -> RecommendResponse:
    """Recommend travel gadgets for a trip.

    Coordinator-entered gadgets for the destination come first, marked
    verified. On top of those the model is asked for a few fresh items that
    avoid everything already on file, so its suggestions never repeat the
    catalog however large it has grown.
    """
    context = await build_trip_context(request)

    catalog = await _load_catalog(context)
    context.existing_gadgets = catalog.existing_names
    context.novel_item_count = _novel_count(context)

    novel: list = []
    live_unavailable = False

    # The provider SDKs block, so the call runs on a worker thread; the
    # backstop timeout covers a retry chain or an SDK that stalls before
    # its own timer starts.
    try:
        novel = await asyncio.wait_for(
            asyncio.to_thread(get_gadget_source().recommend, context),
            timeout=get_env_meta_info().llm_total_timeout_seconds,
        )
    except (TimeoutError, LLMException, GadgetSourceException) as exc:
        # If the catalog already has something to show, a model outage
        # degrades to catalog-only rather than failing the whole request.
        if not catalog.recommendations:
            if isinstance(exc, TimeoutError):
                raise LLMTimeoutException(
                    "The gadget advisor did not answer within the time allowed."
                ) from exc
            raise

        live_unavailable = True
        logger.warning("Serving catalog only; live suggestions failed: %s", exc)

    novel = [_fit_stops(rec, context) for rec in novel]
    recommendations = catalog.recommendations + novel

    sources = list(context.sources)
    if catalog.recommendations:
        sources.append(CATALOG_SOURCE_NAME)
    if novel:
        sources.append(LLM_SOURCE_NAME)

    notes = _context_notes(context)
    notes += _provenance_notes(context, catalog, novel, live_unavailable)

    # A packing list counts once for its trip type and once per destination.
    for i, stop in enumerate(context.stops or []):
        analytics.record_list(stop.name, context.trip.trip_type if i == 0 else None)
    if not context.stops:
        analytics.record_list(context.resolved_place or context.trip.destination, context.trip.trip_type)
    _schedule_suggestions(background, context, novel)

    return RecommendResponse(
        destination=context.trip.destination,
        duration_days=context.trip.duration_days,
        recommendations=recommendations,
        notes=notes,
        sources=sources,
        stops=[_stop_summary(stop) for stop in context.stops],
    )


def _fit_stops(rec, context: TripContext):
    """Keep only the model's "for" names that are real stops of this trip,
    spelled as the trip spells them; none left, or all of them, means the
    item is for the whole trip."""
    if len(context.stops) <= 1 or not rec.stops:
        return rec.model_copy(update={"stops": []}) if rec.stops else rec
    by_name = {s.name.lower(): s.name for s in context.stops}
    stops = list(dict.fromkeys(by_name[n.lower()] for n in rec.stops if n.lower() in by_name))
    if len(stops) == len(context.stops):
        stops = []
    return rec.model_copy(update={"stops": stops})


def _stop_summary(stop) -> StopSummary:
    c = stop.climate
    return StopSummary(
        name=stop.name,
        climate_available=c.available,
        climate_summary=c.summary,
        min_temp_c=c.min_temp_c,
        max_temp_c=c.max_temp_c,
        country_name=stop.country.country_name,
        plug_types=stop.country.plug_types,
        voltage=stop.country.voltage,
        frequency=stop.country.frequency,
    )
