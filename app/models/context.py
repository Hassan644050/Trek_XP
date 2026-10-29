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


class StopContext(BaseModel):
    """One resolved destination of the trip, with its own conditions."""

    name: str
    latitude: float
    longitude: float
    climate: ClimateInfo = Field(default_factory=ClimateInfo)
    country: CountryInfo = Field(default_factory=CountryInfo)


class TripContext(BaseModel):
    """Everything known about a trip, assembled before any gadget source runs.

    Keeping this separate from TripRequest is what lets a GadgetSource be
    swapped (LLM today, community catalog later) without touching the code
    that fetches destination data -- and lets tests build a context literal
    instead of mocking HTTP.
    """

    trip: TripRequest
    # The geocoder's own name for the place. Prompts use this rather than
    # the raw user string, which keeps unvetted input out of the model.
    resolved_place: str | None = None
    # Where the place actually is, so the community catalog can match a
    # stored place to this trip by proximity, not name alone.
    resolved_latitude: float | None = None
    resolved_longitude: float | None = None
    climate: ClimateInfo = Field(default_factory=ClimateInfo)
    country: CountryInfo = Field(default_factory=CountryInfo)
    sources: list[str] = Field(default_factory=list)
    # Gadget names already in the catalog for this location. The model is
    # told to avoid them so its new suggestions do not repeat what
    # coordinators have already entered, however many that is.
    existing_gadgets: list[str] = Field(default_factory=list)
    # How many fresh items to ask the model for. None keeps the open-ended
    # default; the recommend route sets it when it wants exactly N new ones
    # on top of the catalog.
    novel_item_count: int | None = None
    # Every destination of the trip, in order -- one entry for a
    # single-destination trip. The fields above describe the first stop
    # (resolved_place names the whole route when there are several).
    stops: list[StopContext] = Field(default_factory=list)
