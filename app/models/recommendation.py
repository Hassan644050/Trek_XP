from enum import Enum

from pydantic import BaseModel, Field


def normalize_gadget_name(name: str) -> str:
    """A loose key for telling two gadget names apart.

    Used to keep the model's new suggestions from duplicating what the
    catalog already lists: "Power Bank" and "power  bank" are the same item.
    """
    return " ".join(name.lower().split())


class Priority(str, Enum):
    ESSENTIAL = "essential"
    RECOMMENDED = "recommended"
    OPTIONAL = "optional"


class Origin(str, Enum):
    # Where the recommendation itself came from. Community entries are
    # human-reviewed; LLM entries are not, and customers should see which
    # is which.
    LLM = "llm"
    COMMUNITY = "community"


class Recommendation(BaseModel):
    gadget: str
    why: str
    priority: Priority = Priority.RECOMMENDED
    category: str | None = None
    origin: Origin = Origin.LLM
    verified: bool = False
    # Only catalog items have a photo; the model's suggestions are names, so
    # this stays None for them.
    image_url: str | None = None
    # Link to the gadget's public detail page, for catalog items only.
    page_url: str | None = None
    warnings: list[str] = Field(default_factory=list)
    # On a multi-stop trip, the stops this item is for. Empty means the
    # whole trip (and always, for a single-destination trip).
    stops: list[str] = Field(default_factory=list)
    # A model item's one-line catalog description, asked for in the same
    # request as the list so a new suggestion needs no second model call.
    description: str | None = None


class StopSummary(BaseModel):
    """One destination's conditions, for the page to show per stop."""

    name: str
    climate_available: bool
    climate_summary: str | None = None
    min_temp_c: float | None = None
    max_temp_c: float | None = None
    country_name: str | None = None
    plug_types: list[str] = Field(default_factory=list)
    voltage: str | None = None
    frequency: str | None = None


class RecommendResponse(BaseModel):
    destination: str
    duration_days: int
    recommendations: list[Recommendation] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    stops: list[StopSummary] = Field(default_factory=list)
    # True on a quick answer (?quick=1) that skipped the model: the verified
    # items are here, and the model's fresh ones come from the full request.
    pending: bool = False
