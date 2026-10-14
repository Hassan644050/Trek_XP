import asyncio

from fastapi import APIRouter

from app.config import get_env_meta_info
from app.exceptions.exceptions import LLMTimeoutException
from app.models.context import TripContext
from app.models.recommendation import RecommendResponse
from app.models.trip import TripRequest
from app.services.destination.aggregator import build_trip_context
from app.services.gadgets.factory import get_gadget_source


router = APIRouter()

GADGET_SOURCE_NAME = "llm_gadget_knowledge"


def _context_notes(context: TripContext) -> list[str]:
    """Surface what the advice was actually based on.

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

    notes.append(
        "Suggestions come from a language model and have not been "
        "community-verified."
    )

    return notes


@router.post("/recommend", response_model=RecommendResponse)
async def recommend(request: TripRequest) -> RecommendResponse:
    """Recommend travel gadgets for a trip."""
    context = await build_trip_context(request)

    # The provider SDKs are blocking, so they run on a worker thread:
    # calling them inline would stall the event loop for every other
    # request for the whole duration of the model call.
    #
    # The backstop covers what the provider's own per-request timeout does
    # not: a retry chain, or an SDK that stalls before its timer starts. A
    # thread cannot be cancelled, so the worker runs on until the provider
    # gives up -- bounded, because that timeout is shorter than this one.
    try:
        recommendations = await asyncio.wait_for(
            asyncio.to_thread(get_gadget_source().recommend, context),
            timeout=get_env_meta_info().llm_total_timeout_seconds,
        )
    except TimeoutError as exc:
        raise LLMTimeoutException(
            "The gadget advisor did not answer within the time allowed."
        ) from exc

    sources = list(context.sources)

    if recommendations:
        sources.append(GADGET_SOURCE_NAME)

    return RecommendResponse(
        destination=context.trip.destination,
        duration_days=context.trip.duration_days,
        recommendations=recommendations,
        notes=_context_notes(context),
        sources=sources,
    )
