"""Checkout and order contracts.

Prices never come from the browser: a cart line is only a buying option's
id and a quantity, and every amount is worked out on the server from the
database (services/orders.py).
"""

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


OrderStatus = Literal["pending", "confirmed", "shipped", "delivered", "cancelled"]
MAX_LINES = 20


def _tidy(value: str | None) -> str | None:
    return " ".join((value or "").split()) or None


class CartLine(BaseModel):
    variant_id: int = Field(gt=0)
    # Capped again per country (delivery.json max_quantity_per_item).
    quantity: int = Field(default=1, ge=1, le=50)


class QuoteIn(BaseModel):
    items: list[CartLine] = Field(min_length=1, max_length=MAX_LINES)


class QuoteLine(BaseModel):
    variant_id: int
    # "ok", or why it cannot be bought as asked: "out_of_stock" (none left),
    # "not_enough" (fewer than asked; quantity is lowered to what is left),
    # "unavailable" (option deleted, gadget retired, or another currency).
    status: Literal["ok", "out_of_stock", "not_enough", "unavailable"]
    gadget: str | None = None
    gadget_slug: str | None = None
    image_url: str | None = None
    option: str | None = None
    vendor: str | None = None
    unit_price: int = 0
    quantity: int = 0
    available: int = 0
    line_total: int = 0


class DeliveryZone(BaseModel):
    key: str
    label: str
    fee: int
    days: str | None = None


class PaymentMethod(BaseModel):
    key: str
    label: str
    detail: str | None = None


class QuoteOut(BaseModel):
    lines: list[QuoteLine]
    subtotal: int
    currency: str
    zones: list[DeliveryZone]
    payment_methods: list[PaymentMethod]
    max_quantity: int


class CustomerIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    # Checked and normalised per country by the service (01XXXXXXXXX here).
    phone: str = Field(min_length=6, max_length=20)
    email: str | None = Field(default=None, max_length=120)
    address: str = Field(min_length=8, max_length=300)
    area: str = Field(min_length=2, max_length=80)
    delivery_zone: str = Field(min_length=2, max_length=30)
    note: str | None = Field(default=None, max_length=300)

    @field_validator("name", "address", "area", "note")
    @classmethod
    def _clean(cls, value: str | None) -> str | None:
        return _tidy(value)

    @field_validator("email")
    @classmethod
    def _email(cls, value: str | None) -> str | None:
        value = _tidy(value)
        if value and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
            raise ValueError("that email address does not look right")
        return value


class CheckoutIn(BaseModel):
    items: list[CartLine] = Field(min_length=1, max_length=MAX_LINES)
    customer: CustomerIn
    payment_method: Literal["cod"] = "cod"
    # Left empty by people; bots that fill every field give themselves away.
    website: str = Field(default="", max_length=200)


class OrderLineOut(BaseModel):
    gadget_name: str
    option: str
    vendor: str | None = None
    unit_price: int
    quantity: int
    line_total: int


class OrderOut(BaseModel):
    code: str
    status: OrderStatus
    created_at: datetime
    customer_name: str
    phone: str
    email: str | None = None
    address: str
    area: str
    delivery_zone: str
    delivery_label: str
    note: str | None = None
    payment_method: str
    subtotal: int
    delivery_fee: int
    total: int
    currency: str
    lines: list[OrderLineOut]


class OrderSummary(BaseModel):
    """A row of the coordinator's order list."""

    id: int
    code: str
    status: OrderStatus
    created_at: datetime
    customer_name: str
    phone: str
    area: str
    delivery_label: str
    item_count: int
    total: int
    currency: str


class OrderDetail(OrderOut):
    id: int
    updated_at: datetime | None = None
    next_statuses: list[OrderStatus] = Field(default_factory=list)


class OrderStatusIn(BaseModel):
    status: OrderStatus
