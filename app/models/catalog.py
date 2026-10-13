import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.models import Role
from app.models.recommendation import Priority
from app.models.trip import Activity, TripType


# Deliberately loose: real validation is that the admin who creates the
# account knows the address. This only rejects obvious typos.
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _clean(value: str | None) -> str | None:
    if value is None:
        return None

    value = " ".join(value.split())
    return value or None


def _unique(items: list) -> list:
    # Keep the first occurrence, preserving the order the form sent.
    return list(dict.fromkeys(items))


# ---------- auth ----------


class LoginRequest(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    name: str
    role: Role
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime


class UserCreate(BaseModel):
    email: str = Field(max_length=254)
    name: str = Field(min_length=1, max_length=100)
    password: str = Field(max_length=128)
    role: Role = Role.COORDINATOR

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        value = value.strip().lower()

        if not _EMAIL.match(value):
            raise ValueError("Enter a valid email address.")

        return value

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        cleaned = _clean(value)

        if not cleaned:
            raise ValueError("Name is required.")

        return cleaned


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    role: Role | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, max_length=128)


# ---------- catalog ----------


class PlaceIn(BaseModel):
    """A destination: picker result, or coordinator-entered area."""

    name: str = Field(min_length=1, max_length=200)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    country_name: str | None = Field(default=None, max_length=100)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    district: str | None = Field(default=None, max_length=60)
    division: str | None = Field(default=None, max_length=60)

    @field_validator("name")
    @classmethod
    def clean_place_name(cls, value: str) -> str:
        cleaned = _clean(value)

        if not cleaned:
            raise ValueError("Place name is required.")

        return cleaned

    @field_validator("country_code")
    @classmethod
    def upper_code(cls, value: str | None) -> str | None:
        return value.upper() if value else value


class PlaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    country_code: str | None
    country_name: str | None
    latitude: float
    longitude: float
    district: str | None = None
    division: str | None = None


class ManualPlaceIn(BaseModel):
    """A place the geocoders do not know, entered by a coordinator.

    Only the name is typed; the district picks the coordinates, so a
    coordinator never has to find latitude and longitude by hand.
    """

    name: str = Field(min_length=2, max_length=200)
    district: str = Field(min_length=2, max_length=60)

    @field_validator("name")
    @classmethod
    def clean_place_name(cls, value: str) -> str:
        cleaned = _clean(value)

        if not cleaned:
            raise ValueError("Place name is required.")

        return cleaned


class DivisionOut(BaseModel):
    name: str
    districts: list[str]


class AdminAreasOut(BaseModel):
    divisions: list[DivisionOut]


class GadgetIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    category: str | None = Field(default=None, max_length=60)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("name", "category")
    @classmethod
    def collapse_spaces(cls, value: str | None) -> str | None:
        return _clean(value)

    @field_validator("description")
    @classmethod
    def strip_description(cls, value: str | None) -> str | None:
        return (value.strip() or None) if value else None


class GadgetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    category: str | None = Field(default=None, max_length=60)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("name", "category")
    @classmethod
    def collapse_spaces(cls, value: str | None) -> str | None:
        return _clean(value)

    @field_validator("description")
    @classmethod
    def strip_description(cls, value: str | None) -> str | None:
        return (value.strip() or None) if value else None


class PlacementIn(BaseModel):
    place: PlaceIn
    trip_types: list[TripType] = Field(min_length=1)
    activities: list[Activity] = Field(default_factory=list)
    priority: Priority = Priority.RECOMMENDED
    why: str = Field(min_length=3, max_length=300)

    @field_validator("trip_types", "activities")
    @classmethod
    def dedupe(cls, value: list) -> list:
        return _unique(value)

    @field_validator("why")
    @classmethod
    def clean_why(cls, value: str) -> str:
        return " ".join(value.split())


class PlacementUpdate(BaseModel):
    place: PlaceIn | None = None
    trip_types: list[TripType] | None = Field(default=None, min_length=1)
    activities: list[Activity] | None = None
    priority: Priority | None = None
    why: str | None = Field(default=None, min_length=3, max_length=300)

    @field_validator("trip_types", "activities")
    @classmethod
    def dedupe(cls, value: list | None) -> list | None:
        return _unique(value) if value is not None else None


class PlacementOut(BaseModel):
    id: int
    place: PlaceOut
    trip_types: list[TripType]
    activities: list[Activity]
    priority: Priority
    why: str
    updated_at: datetime


class GadgetOut(BaseModel):
    id: int
    name: str
    category: str | None
    description: str | None
    image_url: str | None
    placement_count: int
    updated_at: datetime


class GadgetDetail(GadgetOut):
    placements: list[PlacementOut]


class CatalogOptions(BaseModel):
    """Choices the coordinator form offers, straight from the enums the
    public trip form uses -- so the two can never drift apart."""

    trip_types: list[str]
    activities: list[str]
    priorities: list[str]
