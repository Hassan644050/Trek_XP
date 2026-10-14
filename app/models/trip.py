import re
from datetime import date
from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")[:30]


# Trip types and activities are no longer enums: they are admin-managed and
# live in the database (see app/services/taxonomy.py). Requests carry their
# slug values as plain strings. The forms only offer the active set, and the
# coordinator endpoints validate placement values against it; the traveller
# flow stays loose so a model call never depends on the taxonomy table.


class Baggage(str, Enum):
    # Drives airline power-bank rules: spare lithium batteries are only
    # allowed in the cabin, never in checked luggage. Optional, because the
    # rules only bite on flights and most trips here are by road or rail.
    CARRY_ON_ONLY = "carry_on_only"
    CHECKED = "checked"


class TripRequest(BaseModel):
    """The structured form a customer fills in.

    Deliberately structured rather than free text: it removes the need for an
    entity-extraction LLM call, so a request costs one LLM round trip instead
    of two, and validation happens before any money is spent.
    """

    destination: str = Field(min_length=2, max_length=100)
    start_date: date
    end_date: date
    trip_type: str = Field(min_length=2, max_length=30)
    activities: list[str] = Field(default_factory=list)
    baggage: Baggage | None = None
    travelers: int = Field(default=1, ge=1, le=50)

    @field_validator("trip_type")
    @classmethod
    def _slug_trip_type(cls, value: str) -> str:
        return _slug(value)

    @field_validator("activities")
    @classmethod
    def _slug_activities(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(s for s in (_slug(v) for v in value) if s))

    # Filled in by the destination picker. When present we trust the
    # place the user actually chose instead of re-resolving their text
    # and risking a different match.
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    country_name: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def check_date_order(self) -> "TripRequest":
        if self.end_date < self.start_date:
            raise ValueError("end_date must not be before start_date")

        return self

    @property
    def duration_days(self) -> int:
        return (self.end_date - self.start_date).days + 1
