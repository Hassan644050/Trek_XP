import re
from datetime import datetime

from typing import Literal

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
    # "coordinator", or "model" for a suggestion saved from a traveller's
    # list; review_status is pending / approved / rejected for those.
    origin: str = "coordinator"
    review_status: str | None = None
    suggestion_count: int = 0


class ReviewIn(BaseModel):
    action: Literal["approve", "reject"]


class GadgetBrief(BaseModel):
    """Enough to recognise a gadget in a duplicates list."""

    id: int
    name: str
    category: str | None
    is_active: bool
    origin: str
    review_status: str | None
    placement_count: int
    thumb_url: str | None


class DuplicatePair(BaseModel):
    a: GadgetBrief
    b: GadgetBrief
    # 0-1; 0.8+ is treated as the same item automatically elsewhere.
    score: float


class SimilarGadget(BaseModel):
    gadget: GadgetBrief
    score: float


class MergeIn(BaseModel):
    into_id: int


class DistinctIn(BaseModel):
    a_id: int
    b_id: int


QUALITY_LEVELS = ("budget", "standard", "premium")


class VariantIn(BaseModel):
    brand: str = Field(min_length=1, max_length=80)
    model_name: str | None = Field(default=None, max_length=80)
    color: str | None = Field(default=None, max_length=40)
    quality: str = Field(default="standard")
    price: int = Field(ge=0, le=10_000_000)
    currency: str = Field(default="BDT", min_length=3, max_length=3)
    vendor: str | None = Field(default=None, max_length=80)
    url: str | None = Field(default=None, max_length=300)
    # Units on hand. Required: no option is shown without a confirmed count.
    stock_quantity: int = Field(ge=0, le=100_000)

    @field_validator("brand", "model_name", "color", "vendor")
    @classmethod
    def tidy(cls, value: str | None) -> str | None:
        return _clean(value)

    @field_validator("quality")
    @classmethod
    def known_quality(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in QUALITY_LEVELS:
            raise ValueError(f"quality must be one of {', '.join(QUALITY_LEVELS)}")
        return value

    @field_validator("currency")
    @classmethod
    def upper_currency(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("url")
    @classmethod
    def http_url(cls, value: str | None) -> str | None:
        value = (value or "").strip()
        if not value:
            return None
        if not value.startswith(("http://", "https://")):
            raise ValueError("url must start with http:// or https://")
        return value


class VariantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    brand: str
    model_name: str | None
    color: str | None
    quality: str
    price: int
    currency: str
    vendor: str | None
    url: str | None
    stock_quantity: int
    stock_updated_at: datetime | None = None


class StockIn(BaseModel):
    """Set the units on hand for a buying option (0 = out of stock)."""

    stock_quantity: int = Field(ge=0, le=100_000)


class GadgetDetail(GadgetOut):
    placements: list[PlacementOut]
    variants: list[VariantOut] = []


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


# ---------- home page hero photos ----------


class HeroImageOut(BaseModel):
    id: int
    # "" is the country's default hero; otherwise the destination's URL slug,
    # the same one the home page puts in ?to=<slug>.
    place_slug: str
    place_name: str | None
    alt: str
    small_url: str
    image_url: str
    updated_at: datetime
