from datetime import date
from enum import Enum

from pydantic import BaseModel, Field, model_validator


class TripType(str, Enum):
    HIKING = "hiking"
    BUSINESS = "business"
    BEACH = "beach"
    CITY = "city"
    BACKPACKING = "backpacking"
    WINTER_SPORTS = "winter_sports"


class Activity(str, Enum):
    PHOTOGRAPHY = "photography"
    DIVING = "diving"
    CAMPING = "camping"
    CYCLING = "cycling"
    CLIMBING = "climbing"
    REMOTE_WORK = "remote_work"


class Baggage(str, Enum):
    # Drives airline power-bank rules: spare lithium batteries are only
    # allowed in the cabin, never in checked luggage.
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
    trip_type: TripType
    activities: list[Activity] = Field(default_factory=list)
    baggage: Baggage = Baggage.CHECKED
    travelers: int = Field(default=1, ge=1, le=50)

    @model_validator(mode="after")
    def check_date_order(self) -> "TripRequest":
        if self.end_date < self.start_date:
            raise ValueError("end_date must not be before start_date")

        return self

    @property
    def duration_days(self) -> int:
        return (self.end_date - self.start_date).days + 1
