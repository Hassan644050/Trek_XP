import asyncio
import logging

from fastapi import APIRouter

from app.config import get_env_meta_info
from app.db.engine import get_sessionmaker
from app.exceptions.exceptions import (
    DatabaseNotConfiguredException,
    GadgetSourceException,
    LLMException,
    LLMTimeoutException,
)
from app.models.context import TripContext
from app.models.recommendation import RecommendResponse
from app.models.trip import TripRequest
from app.services.destination.aggregator import build_trip_context
from app.services.gadgets.catalog import CatalogMatch, load_catalog_safely
from app.services.gadgets.factory import get_gadget_source


logger = logging.getLogger(__name__)

router = APIRouter()

LLM_SOURCE_NAME = "llm_gadget_knowledge"
CATALOG_SOURCE_NAME = "community_catalog"

# How many fresh items to ask the model for, on top of the catalog.
NOVEL_ITEMS = 5


def _context_notes(context: TripContext) -> list[str]:
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
        return await load_catalog_safely(db, context)


@router.post("/recommend", response_model=RecommendResponse)
async def recommend(request: TripRequest) -> RecommendResponse:
    """Recommend travel gadgets for a trip.

    Coordinator-entered gadgets for the destination come first, marked
    verified. On top of those the model is asked for a few fresh items that
    avoid everything already on file, so its suggestions never repeat the
    catalog however large it has grown.
    """
    context = await build_trip_context(request)

    catalog = await _load_catalog(context)
    context.existing_gadgets = catalog.existing_names
    context.novel_item_count = NOVEL_ITEMS

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

    recommendations = catalog.recommendations + novel

    sources = list(context.sources)
    if catalog.recommendations:
        sources.append(CATALOG_SOURCE_NAME)
    if novel:
        sources.append(LLM_SOURCE_NAME)

    notes = _context_notes(context)
    notes += _provenance_notes(context, catalog, novel, live_unavailable)

    return RecommendResponse(
        destination=context.trip.destination,
        duration_days=context.trip.duration_days,
        recommendations=recommendations,
        notes=notes,
        sources=sources,
    )
