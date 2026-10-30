"""Checkout and orders without a database: phone numbers, pricing, stock
rules, status changes and the public endpoint's guards.

Locking and stock against a real database live in tests/db/test_orders.py.
"""

import asyncio
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.exceptions.exceptions import InvalidInputException, OutOfStockException
from app.models.orders import CartLine, CheckoutIn, CustomerIn
from app.routes import orders as order_routes
from app.services import orders as svc


BD = svc.delivery_for("BD")


def variant(vid, *, price=1300, stock=3, active=True, currency="BDT", gadget_id=None):
    gadget = SimpleNamespace(id=gadget_id or vid * 10, name=f"Gadget {vid}", slug=f"gadget-{vid}",
                             image_key=None, is_active=active)
    return SimpleNamespace(id=vid, gadget_id=gadget.id, gadget=gadget, brand="Energizer", model_name="Vision",
                           color="Black", quality="standard", price=price, currency=currency,
                           vendor="Shop", stock_quantity=stock)


class FakeDB:
    """Answers scalars() calls in order; records what was added."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.added, self.commits, self.rollbacks = [], 0, 0

    async def scalars(self, query):
        return SimpleNamespace(all=lambda: self.answers.pop(0))

    async def scalar(self, query):
        return None  # no order code taken yet

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


def customer(**overrides):
    fields = dict(name="Hassan Rahman", phone="+880 1712-345678", address="House 12, Road 5, Dhanmondi",
                  area="Dhaka", delivery_zone="inside_dhaka")
    fields.update(overrides)
    return CustomerIn(**fields)


# ---------- rules ----------


@pytest.mark.parametrize("raw,expected", [
    ("01712345678", "01712345678"), ("+8801712345678", "01712345678"), ("880 1712 345678", "01712345678"),
    ("017-1234-5678", "01712345678"), ("01212345678", None), ("0171234567", None), ("hello", None),
])
def test_phone_numbers_are_normalised(raw, expected):
    assert svc.normalize_phone(raw, BD) == expected


def test_delivery_comes_from_country_data():
    assert {z["key"] for z in BD.zones} == {"inside_dhaka", "outside_dhaka"}
    assert [m["key"] for m in BD.payment_methods] == ["cod"]


def test_orders_move_forward_and_only_open_ones_cancel():
    assert svc.NEXT_STATUSES["pending"] == ("confirmed", "cancelled")
    assert "cancelled" not in svc.NEXT_STATUSES["shipped"]
    assert svc.NEXT_STATUSES["delivered"] == () and svc.NEXT_STATUSES["cancelled"] == ()


def test_customer_details_are_checked():
    assert customer(name="  Hassan   Rahman ").name == "Hassan Rahman"
    with pytest.raises(ValidationError):
        customer(email="not-an-email")
    with pytest.raises(ValidationError):
        customer(address="short")


# ---------- pricing ----------


def test_quote_prices_from_the_database_and_flags_stock():
    db = FakeDB([variant(1, price=1300, stock=3), variant(2, stock=0), variant(3, stock=1),
                 variant(4, active=False)])
    lines = asyncio.run(svc.quote(db, [CartLine(variant_id=1, quantity=2), CartLine(variant_id=2),
                                       CartLine(variant_id=3, quantity=4), CartLine(variant_id=4),
                                       CartLine(variant_id=5)], BD))
    by = {line.variant_id: line for line in lines}

    assert (by[1].status, by[1].quantity, by[1].line_total) == ("ok", 2, 2600)
    assert by[2].status == "out_of_stock" and by[2].quantity == 0
    assert (by[3].status, by[3].quantity) == ("not_enough", 1)
    assert by[4].status == "unavailable" and by[5].status == "unavailable"
    assert by[1].option == "Energizer Vision · Black · standard"


def test_quantities_are_capped_per_item():
    lines = asyncio.run(svc.quote(FakeDB([variant(1, stock=50)]), [CartLine(variant_id=1, quantity=40)], BD))
    assert lines[0].quantity == BD.max_quantity


# ---------- placing ----------


def test_placing_takes_stock_and_totals_on_the_server():
    v = variant(1, price=1300, stock=3)
    db = FakeDB([v], [v.gadget])
    order = asyncio.run(svc.place_order(db, CheckoutIn(items=[CartLine(variant_id=1, quantity=2)], customer=customer()), BD))

    assert v.stock_quantity == 1
    assert (order.subtotal, order.delivery_fee, order.total) == (2600, 70, 2670)
    assert order.phone == "01712345678" and order.status == "pending" and order.code.startswith("TXP-")
    assert [(i.gadget_name, i.quantity, i.unit_price) for i in order.items] == [("Gadget 1", 2, 1300)]
    assert db.commits == 1


def test_placing_more_than_is_left_changes_nothing():
    v = variant(1, stock=1)
    db = FakeDB([v], [v.gadget])
    with pytest.raises(OutOfStockException, match="only 1 left"):
        asyncio.run(svc.place_order(db, CheckoutIn(items=[CartLine(variant_id=1, quantity=2)], customer=customer()), BD))
    assert v.stock_quantity == 1 and db.added == [] and db.rollbacks == 1


def test_a_bad_phone_or_zone_is_refused_before_any_stock_is_touched():
    for bad in (customer(phone="0123456789"), customer(delivery_zone="moon")):
        db = FakeDB()
        with pytest.raises(InvalidInputException):
            asyncio.run(svc.place_order(db, CheckoutIn(items=[CartLine(variant_id=1)], customer=bad), BD))


# ---------- the public endpoint ----------


@pytest.fixture
def placed(monkeypatch):
    calls = []

    async def fake_place(db, payload, delivery):
        calls.append(payload)
        from datetime import datetime, timezone
        return SimpleNamespace(code="TXP-ABC234", status="pending", created_at=datetime.now(timezone.utc),
                               customer_name="Hassan", phone="01712345678", email=None, address="House 12, Road 5",
                               area="Dhaka", delivery_zone="inside_dhaka", note=None, payment_method="cod",
                               subtotal=1300, delivery_fee=70, total=1370, currency="BDT", items=[])

    async def no_db():
        yield None

    monkeypatch.setattr(order_routes.order_service, "place_order", fake_place)
    from app.db.engine import get_db
    from app.main import app
    app.dependency_overrides[get_db] = no_db
    order_routes._recent.clear()
    yield calls
    app.dependency_overrides.pop(get_db, None)
    order_routes._recent.clear()


def body(**extra):
    return {"items": [{"variant_id": 8, "quantity": 1}],
            "customer": {"name": "Hassan", "phone": "01712345678", "address": "House 12, Road 5",
                         "area": "Dhaka", "delivery_zone": "inside_dhaka"}, **extra}


def test_checkout_needs_the_same_site_header(client, placed):
    assert client.post("/api/checkout", json=body()).status_code == 403
    response = client.post("/api/checkout", json=body(), headers={"X-Requested-With": "trekxp"})
    assert response.status_code == 201 and response.json()["code"] == "TXP-ABC234"
    assert response.json()["delivery_label"] == "Inside Dhaka city"


def test_bots_and_floods_are_turned_away(client, placed):
    headers = {"X-Requested-With": "trekxp"}
    assert client.post("/api/checkout", json=body(website="http://spam"), headers=headers).status_code == 422
    codes = [client.post("/api/checkout", json=body(), headers=headers).status_code for _ in range(7)]
    assert codes[:order_routes.ORDERS_PER_HOUR] == [201] * order_routes.ORDERS_PER_HOUR
    assert codes[-1] == 429
    assert len(placed) == order_routes.ORDERS_PER_HOUR


def test_prices_cannot_come_from_the_browser():
    payload = CheckoutIn.model_validate(body(price=1, total=1))
    assert not hasattr(payload, "total")
    assert set(payload.items[0].model_dump()) == {"variant_id", "quantity"}
