"""Orders against a real database: stock is taken when an order is placed,
never oversold, and given back when it is cancelled."""

from fastapi.testclient import TestClient

from app.db.models import Gadget, GadgetVariant
from app.main import app
from app.routes import orders as order_routes
from tests.db.conftest import CSRF, run


def make_option(stock: int, price: int = 1300) -> int:
    async def create(session):
        gadget = Gadget(name="Headlamp", slug="headlamp", is_active=True)
        session.add(gadget)
        await session.flush()
        option = GadgetVariant(gadget_id=gadget.id, brand="Energizer", model_name="Vision", color="Black",
                               quality="standard", price=price, currency="BDT", stock_quantity=stock)
        session.add(option)
        await session.commit()
        return option.id

    return run(create)


def stock_of(variant_id: int) -> int:
    async def read(session):
        return (await session.get(GadgetVariant, variant_id)).stock_quantity

    return run(read)


def order(variant_id: int, quantity: int = 1) -> dict:
    return {
        "items": [{"variant_id": variant_id, "quantity": quantity}],
        "customer": {"name": "Hassan Rahman", "phone": "01712345678", "address": "House 12, Road 5, Dhanmondi",
                     "area": "Dhaka", "delivery_zone": "inside_dhaka"},
    }


def test_an_order_takes_stock_and_cancelling_gives_it_back(db_app, coordinator):
    order_routes._recent.clear()
    option = make_option(stock=3)
    public = TestClient(app)

    quote = public.post("/api/checkout/quote", json={"items": [{"variant_id": option, "quantity": 2}]}).json()
    assert (quote["lines"][0]["status"], quote["subtotal"]) == ("ok", 2600)

    placed = public.post("/api/checkout", json=order(option, 2), headers=CSRF)
    assert placed.status_code == 201
    assert (placed.json()["total"], stock_of(option)) == (2670, 1)

    (row,) = coordinator.get("/api/coordinator/orders").json()
    assert (row["code"], row["status"], row["item_count"]) == (placed.json()["code"], "pending", 2)

    detail = coordinator.patch(f"/api/coordinator/orders/{row['id']}", json={"status": "cancelled"}, headers=CSRF)
    assert detail.json()["status"] == "cancelled" and detail.json()["next_statuses"] == []
    assert stock_of(option) == 3


def test_the_last_unit_cannot_be_sold_twice(db_app):
    order_routes._recent.clear()
    option = make_option(stock=1)
    public = TestClient(app)

    first = public.post("/api/checkout", json=order(option), headers=CSRF)
    second = public.post("/api/checkout", json=order(option), headers=CSRF)

    assert first.status_code == 201
    assert second.status_code == 409 and "sold out" in second.json()["detail"]
    assert stock_of(option) == 0


def test_a_shipped_order_cannot_be_cancelled(db_app, coordinator):
    order_routes._recent.clear()
    option = make_option(stock=2)
    TestClient(app).post("/api/checkout", json=order(option), headers=CSRF)
    (row,) = coordinator.get("/api/coordinator/orders").json()

    for step in ("confirmed", "shipped"):
        assert coordinator.patch(f"/api/coordinator/orders/{row['id']}", json={"status": step}, headers=CSRF).status_code == 200
    refused = coordinator.patch(f"/api/coordinator/orders/{row['id']}", json={"status": "cancelled"}, headers=CSRF)
    assert refused.status_code == 422 and stock_of(option) == 1


def test_orders_are_for_staff_only(db_app):
    assert TestClient(app).get("/api/coordinator/orders").status_code == 401
