from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.config import get_env_meta_info
from app.services.destination.geocode import search_destinations


router = APIRouter()


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
