from fastapi import APIRouter

from app.models.context import TripContext
from app.models.recommendation import RecommendResponse
from app.models.trip import TripRequest
from app.services.destination.aggregator import build_trip_context


router = APIRouter()


def _context_notes(context: TripContext) -> list[str]:
    notes: list[str] = []

    if context.climate.available and context.climate.summary:
        notes.append(context.climate.summary)
    else:
        notes.append(
            "Climate data was unavailable for these dates; "
            "recommendations will not account for weather."
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
        "Gadget recommendations are not wired up yet -- destination data only."
    )

    return notes


@router.post("/recommend", response_model=RecommendResponse)
async def recommend(request: TripRequest) -> RecommendResponse:
    """Recommend travel gadgets for a trip.

    Destination data is live; the gadget source is the next step, so
    `recommendations` comes back empty for now.
    """
    context = await build_trip_context(request)

    return RecommendResponse(
        destination=context.trip.destination,
        duration_days=context.trip.duration_days,
        recommendations=[],
        notes=_context_notes(context),
        sources=context.sources,
    )
