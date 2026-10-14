import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.models import Role
from app.models.recommendation import Priority


# Deliberately loose: real validation is that the admin who creates the
# account knows the address. This only rejects obvious typos.
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _clean(value: str | None) -> str | None:
    if value is None:
        return None

    value = " ".join(value.split())
    return value or None


def _slug_list(items: list[str] | None) -> list[str] | None:
    if items is None:
        return None
    import re
    cleaned = (re.sub(r"[^a-z0-9]+", "_", v.strip().lower()).strip("_")[:30] for v in items)
    return list(dict.fromkeys(c for c in cleaned if c))


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


# protected_namespaces=() because of the model_name field: Pydantic reserves
# the model_ prefix, and while the pinned version does not warn on it, this
# keeps an upgrade from turning that into noise.
class GadgetIn(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    name: str = Field(min_length=2, max_length=120)
    brand: str | None = Field(default=None, max_length=80)
    model_name: str | None = Field(default=None, max_length=80)
    category: str | None = Field(default=None, max_length=60)
    color: str | None = Field(default=None, max_length=40)
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool = True

    @field_validator("name", "brand", "model_name", "category", "color")
    @classmethod
    def collapse_spaces(cls, value: str | None) -> str | None:
        return _clean(value)

    @field_validator("description")
    @classmethod
    def strip_description(cls, value: str | None) -> str | None:
        return (value.strip() or None) if value else None


class GadgetUpdate(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    name: str | None = Field(default=None, min_length=2, max_length=120)
    brand: str | None = Field(default=None, max_length=80)
    model_name: str | None = Field(default=None, max_length=80)
    category: str | None = Field(default=None, max_length=60)
    color: str | None = Field(default=None, max_length=40)
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None

    @field_validator("name", "brand", "model_name", "category", "color")
    @classmethod
    def collapse_spaces(cls, value: str | None) -> str | None:
        return _clean(value)

    @field_validator("description")
    @classmethod
    def strip_description(cls, value: str | None) -> str | None:
        return (value.strip() or None) if value else None


class PlacementIn(BaseModel):
    place: PlaceIn
    # Slugs validated against the active trip types / activities in the
    # coordinator route, where a database session is available.
    trip_types: list[str] = Field(min_length=1)
    activities: list[str] = Field(default_factory=list)
    priority: Priority = Priority.RECOMMENDED
    why: str = Field(min_length=3, max_length=300)

    @field_validator("trip_types", "activities")
    @classmethod
    def clean(cls, value: list) -> list:
        return _slug_list(value)

    @field_validator("why")
    @classmethod
    def clean_why(cls, value: str) -> str:
        return " ".join(value.split())


class PlacementUpdate(BaseModel):
    place: PlaceIn | None = None
    trip_types: list[str] | None = Field(default=None, min_length=1)
    activities: list[str] | None = None
    priority: Priority | None = None
    why: str | None = Field(default=None, min_length=3, max_length=300)

    @field_validator("trip_types", "activities")
    @classmethod
    def clean(cls, value: list | None) -> list | None:
        return _slug_list(value)


class PlacementOut(BaseModel):
    id: int
    place: PlaceOut
    trip_types: list[str]
    activities: list[str]
    priority: Priority
    why: str
    updated_at: datetime


class GadgetOut(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    id: int
    name: str
    brand: str | None
    model_name: str | None
    category: str | None
    color: str | None
    description: str | None
    is_active: bool
    # One URL per rendition, so each page can request the size it shows
    # instead of downloading the largest one and scaling it in the browser.
    thumb_url: str | None
    detail_url: str | None
    image_url: str | None
    placement_count: int
    updated_at: datetime


class GadgetDetail(GadgetOut):
    placements: list[PlacementOut]


class Option(BaseModel):
    """An admin-managed choice: the slug stored/sent, and its display label."""

    value: str
    label: str


class CatalogOptions(BaseModel):
    """Choices the forms offer, read from the admin-managed tables so the
    traveller and coordinator forms can never drift apart."""

    trip_types: list[Option]
    activities: list[Option]
    priorities: list[str]


# ---------- admin: catalog settings ----------


class OptionAdmin(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    value: str
    label: str
    is_active: bool
    sort_order: int


class OptionCreate(BaseModel):
    label: str = Field(min_length=1, max_length=60)


class OptionUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=60)
    is_active: bool | None = None


class DivisionRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    country_code: str
    name: str


class DivisionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)


class DestinationRow(BaseModel):
    id: int
    name: str
    latitude: float
    longitude: float
    division: str | None
    country_code: str | None
    placement_count: int


class DestinationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    division: str = Field(min_length=1, max_length=60)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)

    @field_validator("name", "division")
    @classmethod
    def tidy(cls, value: str) -> str:
        return " ".join(value.split())
