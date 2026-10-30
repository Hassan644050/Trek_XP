"""Saved bag contracts (services/bags.py)."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator


MAX_BAG_ITEMS = 30


class BagItemIn(BaseModel):
    """One gadget of a bag, as the browser holds it. Only references and a
    name: prices, photos and stock are looked up when the bag is opened."""

    name: str = Field(min_length=1, max_length=120)
    # The gadget's page slug, when it has one (from /gadget/<slug>).
    slug: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9-]{0,139}$")
    variant_id: int | None = Field(default=None, gt=0)
    priority: Literal["essential", "recommended", "optional"] | None = None

    @field_validator("name")
    @classmethod
    def _tidy(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("a gadget needs a name")
        return value


class SaveBagIn(BaseModel):
    items: list[BagItemIn] = Field(min_length=1, max_length=MAX_BAG_ITEMS)


class SavedBagOut(BaseModel):
    code: str
    url: str
    count: int


class BagOption(BaseModel):
    id: int
    brand: str
    model_name: str | None = None
    color: str | None = None
    quality: str | None = None
    price: int
    currency: str
    vendor: str | None = None
    stock: str          # "in" / "low" / "out"
    stock_label: str    # "In stock", "Only 2 left", "Out of stock"


class BagItemView(BaseModel):
    name: str
    slug: str | None = None        # set only for an active catalog gadget
    image_url: str | None = None
    # The photo's storage key, for the preview card; never sent out.
    image_key: str | None = Field(default=None, exclude=True)
    category: str | None = None
    priority: str | None = None
    option: BagOption | None = None


class BagView(BaseModel):
    code: str
    items: list[BagItemView]
    # The chosen options' prices added up (each counted once).
    chosen_total: int = 0
    currency: str = "BDT"
