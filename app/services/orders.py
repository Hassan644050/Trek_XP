"""Checkout: pricing a cart, placing an order, and moving it along.

Rules that keep it honest:
- Amounts come from the database, never the browser: a cart is buying
  option ids and quantities.
- Stock is taken when the order is placed, inside one transaction with the
  options' rows locked (SELECT ... FOR UPDATE, in id order so two orders
  cannot deadlock). Two people cannot both buy the last unit.
- Cancelling gives the stock back. Shipped or delivered orders cannot be
  cancelled here -- that is a return, handled by hand.
- Delivery zones, fees, payment methods and the phone rule are country data
  (app/data/countries/<code>/delivery.json), not code.
"""

import json
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.models import Gadget, GadgetVariant, Order, OrderItem
from app.exceptions.exceptions import (
    InvalidInputException,
    OutOfStockException,
    ResourceNotFoundException,
)
from app.models.orders import CartLine, CheckoutIn, QuoteLine
from app.services.destination.countries import get_country, home_country
from app.services.media.storage import get_image_storage, variant_key
from app.services.media.variants import THUMB


# What a coordinator can move an order to from each status.
NEXT_STATUSES: dict[str, tuple[str, ...]] = {
    "pending": ("confirmed", "cancelled"),
    "confirmed": ("shipped", "cancelled"),
    "shipped": ("delivered",),
    "delivered": (),
    "cancelled": (),
}

# Order codes: no 0/O or 1/I/L, so they survive being read out on a call.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


@dataclass(frozen=True)
class Delivery:
    currency: str
    zones: list[dict]
    payment_methods: list[dict]
    max_quantity: int
    phone_pattern: str
    phone_prefix: str
    support_phone: str | None = None  # whom customers call about an order

    def zone(self, key: str) -> dict | None:
        return next((z for z in self.zones if z["key"] == key), None)


@lru_cache(maxsize=8)
def delivery_for(country_code: str | None = None) -> Delivery:
    country = get_country(country_code) or home_country()
    data = json.loads((country.directory / "delivery.json").read_text(encoding="utf-8"))
    return Delivery(
        currency=data["currency"],
        zones=data["zones"],
        payment_methods=data["payment_methods"],
        max_quantity=int(data.get("max_quantity_per_item", 5)),
        phone_pattern=data["phone"]["pattern"],
        phone_prefix=data["phone"].get("country_prefix", ""),
        support_phone=(data.get("support") or {}).get("phone"),
    )


def normalize_phone(raw: str, delivery: Delivery) -> str | None:
    """The number in its local form ("01712345678"), or None if it is not a
    valid mobile number here. Accepts spaces, dashes and +880 / 880."""
    digits = re.sub(r"\D", "", raw or "")
    prefix = delivery.phone_prefix
    if prefix and digits.startswith(prefix) and len(digits) > len(prefix) + 8:
        digits = "0" + digits[len(prefix):].lstrip("0")
    return digits if re.fullmatch(delivery.phone_pattern, digits) else None


def option_label(variant: GadgetVariant) -> str:
    name = " ".join(p for p in (variant.brand, variant.model_name) if p)
    return " · ".join(p for p in (name, variant.color, variant.quality) if p)


def _thumb(image_key: str | None) -> str | None:
    return get_image_storage().url(variant_key(image_key, THUMB.name)) if image_key else None


def _merge(lines: list[CartLine], delivery: Delivery) -> dict[int, int]:
    """Quantities per option: repeats added up, each capped."""
    wanted: dict[int, int] = {}
    for line in lines:
        wanted[line.variant_id] = wanted.get(line.variant_id, 0) + line.quantity
    return {vid: min(qty, delivery.max_quantity) for vid, qty in wanted.items()}


def _sellable(variant: GadgetVariant | None, delivery: Delivery) -> bool:
    return (
        variant is not None
        and variant.gadget is not None
        and variant.gadget.is_active
        and variant.currency == delivery.currency
    )


async def quote(db, lines: list[CartLine], delivery: Delivery) -> list[QuoteLine]:
    """Today's price and availability for each line of a cart."""
    wanted = _merge(lines, delivery)
    rows = (
        await db.scalars(
            select(GadgetVariant)
            .where(GadgetVariant.id.in_(wanted))
            .options(selectinload(GadgetVariant.gadget))
        )
    ).all()
    by_id = {v.id: v for v in rows}

    out: list[QuoteLine] = []
    for variant_id, asked in wanted.items():
        variant = by_id.get(variant_id)
        if not _sellable(variant, delivery):
            out.append(QuoteLine(variant_id=variant_id, status="unavailable"))
            continue

        stock = max(variant.stock_quantity or 0, 0)
        quantity = min(asked, stock)
        status = "ok" if quantity == asked else ("out_of_stock" if stock == 0 else "not_enough")
        out.append(QuoteLine(
            variant_id=variant_id, status=status,
            gadget=variant.gadget.name, gadget_slug=variant.gadget.slug,
            image_url=_thumb(variant.gadget.image_key),
            option=option_label(variant), vendor=variant.vendor,
            unit_price=variant.price, quantity=quantity,
            available=min(stock, delivery.max_quantity),
            line_total=variant.price * quantity,
        ))
    return out


async def _new_code(db) -> str:
    while True:
        code = "TXP-" + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))
        if not await db.scalar(select(Order.id).where(Order.code == code)):
            return code


async def place_order(db, payload: CheckoutIn, delivery: Delivery) -> Order:
    """Create the order and take its stock, all or nothing."""
    customer = payload.customer
    phone = normalize_phone(customer.phone, delivery)
    if phone is None:
        raise InvalidInputException("Please give a valid mobile number, like 01712345678.")
    zone = delivery.zone(customer.delivery_zone)
    if zone is None:
        raise InvalidInputException("Please choose where we should deliver.")
    if payload.payment_method not in {m["key"] for m in delivery.payment_methods}:
        raise InvalidInputException("That payment method is not available.")

    wanted = _merge(payload.items, delivery)
    # Locked in id order: two orders for the same options wait in line
    # instead of deadlocking.
    variants = (
        await db.scalars(
            select(GadgetVariant)
            .where(GadgetVariant.id.in_(wanted))
            .order_by(GadgetVariant.id)
            .with_for_update(of=GadgetVariant)
        )
    ).all()
    by_id = {v.id: v for v in variants}
    gadgets = {
        g.id: g for g in (await db.scalars(
            select(Gadget).where(Gadget.id.in_({v.gadget_id for v in variants}))
        )).all()
    }

    problems: list[str] = []
    for variant_id, qty in wanted.items():
        variant = by_id.get(variant_id)
        gadget = gadgets.get(variant.gadget_id) if variant else None
        if variant is None or gadget is None or not gadget.is_active or variant.currency != delivery.currency:
            problems.append("An item in your bag is no longer sold here.")
        elif variant.stock_quantity < qty:
            left = max(variant.stock_quantity, 0)
            problems.append(f"{gadget.name} ({option_label(variant)}): "
                            + (f"only {left} left." if left else "sold out."))
    if problems:
        await db.rollback()
        raise OutOfStockException(" ".join(problems) + " Please review your order.")

    order = Order(
        code=await _new_code(db),
        status="pending",
        # Set here rather than by the database: sessions do not reload after
        # a commit, and the confirmation shows the time.
        created_at=datetime.now(timezone.utc),
        customer_name=customer.name,
        phone=phone,
        email=customer.email,
        address=customer.address,
        area=customer.area,
        delivery_zone=zone["key"],
        note=customer.note,
        payment_method=payload.payment_method,
        currency=delivery.currency,
        subtotal=0, delivery_fee=int(zone["fee"]), total=0,
        items=[],
    )
    for variant_id, qty in wanted.items():
        variant = by_id[variant_id]
        variant.stock_quantity -= qty
        order.items.append(OrderItem(
            variant_id=variant.id,
            gadget_name=gadgets[variant.gadget_id].name,
            option=option_label(variant)[:200],
            vendor=variant.vendor,
            unit_price=variant.price,
            quantity=qty,
            line_total=variant.price * qty,
        ))
    order.subtotal = sum(i.line_total for i in order.items)
    order.total = order.subtotal + order.delivery_fee

    db.add(order)
    await db.commit()
    return order


async def change_status(db, order_id: int, status: str, user_id: int | None) -> Order:
    """Move an order on; cancelling puts its stock back."""
    order = await db.scalar(
        select(Order).where(Order.id == order_id).options(selectinload(Order.items)).with_for_update(of=Order)
    )
    if order is None:
        raise ResourceNotFoundException("That order no longer exists.")
    if status == order.status:
        return order
    if status not in NEXT_STATUSES[order.status]:
        raise InvalidInputException(f"A {order.status} order cannot be marked {status}.")

    if status == "cancelled":
        ids = sorted({i.variant_id for i in order.items if i.variant_id})
        variants = {
            v.id: v for v in (await db.scalars(
                select(GadgetVariant).where(GadgetVariant.id.in_(ids))
                .order_by(GadgetVariant.id).with_for_update()
            )).all()
        }
        for item in order.items:
            if item.variant_id in variants:  # a deleted option has nothing to restock
                variants[item.variant_id].stock_quantity += item.quantity

    order.status = status
    order.updated_at = datetime.now(timezone.utc)
    order.updated_by_id = user_id
    await db.commit()
    return order
