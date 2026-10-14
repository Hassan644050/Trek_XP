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
    warnings: list[str] = Field(default_factory=list)


class RecommendResponse(BaseModel):
    destination: str
    duration_days: int
    recommendations: list[Recommendation] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
