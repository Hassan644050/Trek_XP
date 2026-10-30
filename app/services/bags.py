"""Saved bags: a bag kept as a short link (/bag/<code>).

Saving stores references -- a gadget's slug and the chosen option's id --
plus the name, so opening the link shows today's catalog: current names,
photos, prices and stock. A slug that no longer leads to an active gadget,
or an option that was deleted or moved, just falls back to the name.

Gadgets without a catalog page (the model's suggestions) are kept by name
only. Those names come from the browser, so the page shows them as plain
text, never in the link's preview card.
"""

import secrets
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from app.db.models import Gadget, SavedBag
from app.models.bags import BagItemView, BagOption, BagView, SaveBagIn
from app.services.gadgets.similarity import is_same
from app.services.gadgets.stock import can_buy, stock_status
from app.services.media.storage import get_image_storage, variant_key
from app.services.media.variants import THUMB


# No 0/O or 1/I/L: codes get read out and typed.
_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
CODE_LENGTH = 6


async def save(db, payload: SaveBagIn) -> SavedBag:
    seen: set[str] = set()
    items = []
    for item in payload.items:
        key = (item.slug or item.name).lower()
        if key in seen:
            continue  # the same gadget twice is one line
        seen.add(key)
        items.append(item.model_dump())

    while True:
        code = "".join(secrets.choice(_ALPHABET) for _ in range(CODE_LENGTH))
        if await db.get(SavedBag, code) is None:
            break
    bag = SavedBag(code=code, items=items, created_at=datetime.now(timezone.utc), open_count=0)
    db.add(bag)
    await db.commit()
    return bag


async def active_gadgets(db) -> list[Gadget]:
    return list((await db.scalars(
        select(Gadget).where(Gadget.is_active.is_(True), Gadget.slug.is_not(None))
        .options(selectinload(Gadget.variants))
    )).all())


def availability(gadgets: list[Gadget]) -> dict[str, dict]:
    """For every active gadget: how many buying options its compare page
    has, which are in stock, and the lowest price in stock.

    Counted over the same group as the compare page (the gadget and every
    active gadget that is the same item), since that is the page a bag item
    opens. CPU only; the caller decides where it runs.
    """
    out: dict[str, dict] = {}
    for gadget in gadgets:
        group = [g for g in gadgets if g.id == gadget.id or is_same(g.name, gadget.name)]
        options = [v for g in group for v in g.variants]
        in_stock = [v for v in options if can_buy(v.stock_quantity)]
        cheapest = min(in_stock, key=lambda v: v.price, default=None)
        out[gadget.slug] = {
            "options": len(options),
            "in_stock": len(in_stock),
            "in_stock_ids": sorted(v.id for v in in_stock),
            "from_price": cheapest.price if cheapest else None,
            "currency": cheapest.currency if cheapest else None,
        }
    return out


async def load(db, code: str, *, count_open: bool = True) -> BagView | None:
    bag = await db.get(SavedBag, code)
    if bag is None:
        return None

    slugs = {i["slug"] for i in bag.items if i.get("slug")}
    gadgets = {
        g.slug: g for g in (await db.scalars(
            select(Gadget).where(Gadget.slug.in_(slugs), Gadget.is_active.is_(True))
            .options(selectinload(Gadget.variants))
        )).all()
    } if slugs else {}
    storage = get_image_storage()

    views: list[BagItemView] = []
    total, currency = 0, "BDT"
    for item in bag.items:
        gadget = gadgets.get(item.get("slug"))
        if gadget is None:
            views.append(BagItemView(name=item["name"], priority=item.get("priority")))
            continue

        option = None
        variant = next((v for v in gadget.variants if v.id == item.get("variant_id")), None)
        if variant is not None:
            stock, label = stock_status(variant.stock_quantity)
            option = BagOption(
                id=variant.id, brand=variant.brand, model_name=variant.model_name, color=variant.color,
                quality=variant.quality, price=variant.price, currency=variant.currency,
                vendor=variant.vendor, stock=stock, stock_label=label,
            )
            total += variant.price
            currency = variant.currency
        views.append(BagItemView(
            name=gadget.name, slug=gadget.slug, category=gadget.category, priority=item.get("priority"),
            image_url=storage.url(variant_key(gadget.image_key, THUMB.name)) if gadget.image_key else None,
            image_key=gadget.image_key,
            option=option,
        ))

    if count_open:
        await db.execute(
            update(SavedBag).where(SavedBag.code == code)
            .values(open_count=SavedBag.open_count + 1, opened_at=datetime.now(timezone.utc))
        )
        await db.commit()
    return BagView(code=code, items=views, chosen_total=total, currency=currency)
