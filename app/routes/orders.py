"""Checkout (public) and order handling (coordinators).

Public:
- POST /api/checkout/quote   today's prices and stock for a cart, plus the
                             delivery zones and payment methods
- POST /api/checkout         place the order (cash on delivery)

Coordinators:
- GET   /api/coordinator/orders          every order, newest first
- GET   /api/coordinator/orders/{id}     one order in full
- PATCH /api/coordinator/orders/{id}     move it on (confirm, ship, ...)

The logic lives in services/orders.py; this module checks who may call what
and shapes the answers.
"""

import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import check_csrf, require_coordinator
from app.db.engine import get_db
from app.db.models import Order, OrderItem, User
from app.exceptions.exceptions import InvalidInputException, ResourceNotFoundException, TooManyRequestsException
from app.models.orders import (
    CheckoutIn,
    DeliveryZone,
    OrderDetail,
    OrderLineOut,
    OrderOut,
    OrderStatusIn,
    OrderSummary,
    PaymentMethod,
    QuoteIn,
    QuoteOut,
)
from app.services import orders as order_service


checkout_router = APIRouter(prefix="/api/checkout", tags=["checkout"])
orders_router = APIRouter(prefix="/api/coordinator", tags=["orders"])

# A public endpoint that writes: a few orders per visitor per hour is plenty
# for a real customer and stops a script filling the order list.
ORDERS_PER_HOUR = 5
_recent: dict[str, deque] = defaultdict(deque)


def _rate_limit(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    seen = _recent[ip]
    while seen and now - seen[0] > 3600:
        seen.popleft()
    if len(seen) >= ORDERS_PER_HOUR:
        raise TooManyRequestsException(
            "Too many orders from this connection. Please call us, or try again later."
        )
    seen.append(now)


def _zone_label(code: str) -> str:
    zone = order_service.delivery_for().zone(code)
    return zone["label"] if zone else code


def _order_out(order: Order) -> dict:
    return dict(
        code=order.code, status=order.status, created_at=order.created_at,
        customer_name=order.customer_name, phone=order.phone, email=order.email,
        address=order.address, area=order.area,
        delivery_zone=order.delivery_zone, delivery_label=_zone_label(order.delivery_zone),
        note=order.note, payment_method=order.payment_method,
        subtotal=order.subtotal, delivery_fee=order.delivery_fee, total=order.total,
        currency=order.currency,
        lines=[OrderLineOut(gadget_name=i.gadget_name, option=i.option, vendor=i.vendor,
                            unit_price=i.unit_price, quantity=i.quantity, line_total=i.line_total)
               for i in order.items],
    )


def _order_detail(order: Order) -> OrderDetail:
    return OrderDetail(
        id=order.id, updated_at=order.updated_at,
        next_statuses=list(order_service.NEXT_STATUSES.get(order.status, ())),
        **_order_out(order),
    )


# ---------- public ----------


@checkout_router.post("/quote", response_model=QuoteOut)
async def checkout_quote(payload: QuoteIn, db: AsyncSession = Depends(get_db)) -> QuoteOut:
    delivery = order_service.delivery_for()
    lines = await order_service.quote(db, payload.items, delivery)
    return QuoteOut(
        lines=lines,
        subtotal=sum(line.line_total for line in lines),
        currency=delivery.currency,
        zones=[DeliveryZone(**z) for z in delivery.zones],
        payment_methods=[PaymentMethod(**m) for m in delivery.payment_methods],
        max_quantity=delivery.max_quantity,
        support_phone=delivery.support_phone,
    )


@checkout_router.post("", response_model=OrderOut, status_code=201)
async def place_order(
    payload: CheckoutIn, request: Request, db: AsyncSession = Depends(get_db)
) -> OrderOut:
    # Same-site only: the checkout page sends the header, a form on another
    # site cannot.
    check_csrf(request)
    if payload.website:
        raise InvalidInputException("Your order could not be placed.")
    _rate_limit(request)

    order = await order_service.place_order(db, payload, order_service.delivery_for())
    return OrderOut(**_order_out(order))


# ---------- coordinators ----------


@orders_router.get("/orders", response_model=list[OrderSummary])
async def list_orders(
    db: AsyncSession = Depends(get_db), _: User = Depends(require_coordinator),
) -> list[OrderSummary]:
    counts = dict((await db.execute(
        select(OrderItem.order_id, func.sum(OrderItem.quantity)).group_by(OrderItem.order_id)
    )).all())
    orders = (await db.scalars(select(Order).order_by(Order.created_at.desc()).limit(1000))).all()
    return [
        OrderSummary(
            id=o.id, code=o.code, status=o.status, created_at=o.created_at,
            customer_name=o.customer_name, phone=o.phone, area=o.area,
            delivery_label=_zone_label(o.delivery_zone),
            item_count=int(counts.get(o.id) or 0), total=o.total, currency=o.currency,
        )
        for o in orders
    ]


@orders_router.get("/orders/{order_id}", response_model=OrderDetail)
async def get_order(
    order_id: int, db: AsyncSession = Depends(get_db), _: User = Depends(require_coordinator),
) -> OrderDetail:
    order = await db.scalar(select(Order).where(Order.id == order_id).options(selectinload(Order.items)))
    if order is None:
        raise ResourceNotFoundException("That order no longer exists.")
    return _order_detail(order)


@orders_router.patch("/orders/{order_id}", response_model=OrderDetail)
async def update_order(
    order_id: int,
    payload: OrderStatusIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_coordinator),
) -> OrderDetail:
    order = await order_service.change_status(db, order_id, payload.status, user.id)
    return _order_detail(order)
