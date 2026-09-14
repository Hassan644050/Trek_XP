from fastapi import APIRouter, status
from fastapi.exceptions import HTTPException

from app.models.recommendation import RecommendResponse
from app.models.trip import TripRequest


router = APIRouter()


@router.post("/recommend", response_model=RecommendResponse)
def recommend(request: TripRequest) -> RecommendResponse:
    """Recommend travel gadgets for a trip.

    The request and response shapes are settled; the pipeline behind them
    (destination lookup -> gadget source -> guardrails) is not wired yet.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=(
            "Recommendation pipeline not implemented yet. "
            "Next: destination services, then LLMGadgetSource."
        ),
    )
