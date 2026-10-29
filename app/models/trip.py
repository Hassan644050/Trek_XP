import re
from datetime import date
from enum import Enum

from typing import Literal

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


MAX_STOPS = 5
MAX_TRIP_TYPES = 4


class StopIn(BaseModel):
    """One destination of a multi-stop trip, as the picker supplies it."""

    name: str = Field(min_length=2, max_length=100)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    country_name: str | None = Field(default=None, max_length=100)


# Who is travelling. Optional: it only steers the model towards
# gender-specific items where they genuinely matter, and is never stored.
Gender = Literal["female", "male", "mixed"]


class TripRequest(BaseModel):
    """The structured form a customer fills in.

    Deliberately structured rather than free text: it removes the need for an
    entity-extraction LLM call, so a request costs one LLM round trip instead
    of two, and validation happens before any money is spent.
    """

    # One place, or -- with `stops` -- a label for the whole route, filled in
    # from the stops when left out.
    destination: str | None = Field(default=None, min_length=2, max_length=300)
    # Several destinations visited on one trip, in order. Empty for a
    # single-destination trip, which uses `destination` and the coordinates.
    stops: list[StopIn] = Field(default_factory=list, max_length=MAX_STOPS)
    gender: Gender | None = None
    start_date: date
    end_date: date
    # One or more kinds of trip (a beach-and-hiking trip is both). Send
    # `trip_types`, or the older single `trip_type`; after validation both
    # are set and trip_type is the first of trip_types.
    trip_types: list[str] = Field(default_factory=list, max_length=MAX_TRIP_TYPES)
    trip_type: str | None = Field(default=None, min_length=2, max_length=30)
    activities: list[str] = Field(default_factory=list, max_length=12)
    baggage: Baggage | None = None
    travelers: int = Field(default=1, ge=1, le=50)

    @field_validator("trip_type")
    @classmethod
    def _slug_trip_type(cls, value: str | None) -> str | None:
        return _slug(value) if value is not None else None

    @field_validator("trip_types")
    @classmethod
    def _slug_trip_types(cls, value: list[str]) -> list[str]:
        slugs = [_slug(v) for v in value]
        if any(len(s) < 2 for s in slugs):
            raise ValueError("each trip type needs at least 2 letters")
        return list(dict.fromkeys(slugs))

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

    @model_validator(mode="after")
    def settle_trip_types(self) -> "TripRequest":
        if not self.trip_types and self.trip_type:
            self.trip_types = [self.trip_type]
        if not self.trip_types:
            raise ValueError("pick at least one trip type")
        self.trip_type = self.trip_types[0]
        return self

    @model_validator(mode="after")
    def name_the_trip(self) -> "TripRequest":
        if self.stops and not self.destination:
            self.destination = " + ".join(s.name for s in self.stops)[:300]
        if not self.destination:
            raise ValueError("give a destination, or one or more stops")
        return self

    @property
    def duration_days(self) -> int:
        return (self.end_date - self.start_date).days + 1
