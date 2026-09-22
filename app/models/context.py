from pydantic import BaseModel, Field

from app.models.trip import TripRequest


class ClimateInfo(BaseModel):
    summary: str | None = None
    avg_temp_c: float | None = None
    min_temp_c: float | None = None
    max_temp_c: float | None = None
    precipitation_mm: float | None = None
    # True when the figures are last year's actuals standing in for a trip
    # too far out to forecast -- callers should say so rather than imply
    # these are predictions.
    historical: bool = False
    available: bool = True


class CountryInfo(BaseModel):
    country_name: str | None = None
    country_code: str | None = None
    plug_types: list[str] = Field(default_factory=list)
    voltage: str | None = None
    frequency: str | None = None
    available: bool = True


class TripContext(BaseModel):
    """Everything known about a trip, assembled before any gadget source runs.

    Keeping this separate from TripRequest is what lets a GadgetSource be
    swapped (LLM today, community catalog later) without touching the code
    that fetches destination data -- and lets tests build a context literal
    instead of mocking HTTP.
    """

    trip: TripRequest
    climate: ClimateInfo = Field(default_factory=ClimateInfo)
    country: CountryInfo = Field(default_factory=CountryInfo)
    sources: list[str] = Field(default_factory=list)
