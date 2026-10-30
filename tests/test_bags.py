"""Saved bags without a database: what is accepted, the page, the guards."""

import asyncio
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.models.bags import BagItemView, BagOption, BagView, SaveBagIn
from app.routes import bags as bag_routes
from app.services import bags as svc


def test_only_references_and_a_name_are_kept():
    payload = SaveBagIn.model_validate({"items": [
        {"name": "  Head   lamp ", "slug": "headlamp", "variant_id": 8, "priority": "essential", "price": 1},
    ]})
    assert payload.items[0].model_dump() == {"name": "Head lamp", "slug": "headlamp", "variant_id": 8,
                                             "priority": "essential"}
    for bad in ({"name": "x", "slug": "../admin"}, {"name": "x", "variant_id": 0}, {"name": "   "}):
        with pytest.raises(ValidationError):
            SaveBagIn.model_validate({"items": [bad]})
    with pytest.raises(ValidationError):
        SaveBagIn.model_validate({"items": [{"name": f"g{i}"} for i in range(31)]})


def test_the_same_gadget_twice_is_saved_once():
    class DB:
        added = []

        async def get(self, model, key):
            return None

        def add(self, obj):
            self.added.append(obj)

        async def commit(self):
            pass

    payload = SaveBagIn.model_validate({"items": [{"name": "Headlamp", "slug": "headlamp"},
                                                  {"name": "HEADLAMP", "slug": "headlamp"},
                                                  {"name": "Leech socks"}]})
    bag = asyncio.run(svc.save(DB(), payload))
    assert [i["name"] for i in bag.items] == ["Headlamp", "Leech socks"]
    assert len(bag.code) == svc.CODE_LENGTH and bag_routes.CODE.fullmatch(bag.code)


def view():
    return BagView(code="k7q2mx", chosen_total=1300, items=[
        BagItemView(name="Headlamp", slug="headlamp", image_url="/media/h_thumb.webp", priority="essential",
                    option=BagOption(id=8, brand="Energizer", model_name="Vision", color="Black", quality="standard",
                                     price=1300, currency="BDT", vendor="Daraz", stock="in", stock_label="In stock")),
        BagItemView(name='<script>alert(1)</script> FREE MONEY'),
    ])


def test_the_page_shows_todays_details_and_keeps_browser_text_plain():
    request = SimpleNamespace(base_url="https://trekxp.example/", url="https://trekxp.example/bag/k7q2mx")
    page = bag_routes._render(request, view())

    assert "Travel bag · 2 gadgets" in page and "৳1,300" in page and "In stock" in page
    assert '<a href="/compare/headlamp">Compare options</a>' in page
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page
    # The preview text and card name catalog gadgets only.
    description = page.split('og:description" content="')[1].split('"')[0]
    assert "Headlamp" in description and "FREE MONEY" not in description
    assert 'content="noindex"' in page
    assert "https://trekxp.example/share/bag/k7q2mx.png" in page


@pytest.fixture
def saving(monkeypatch):
    async def fake_save(db, payload):
        return SimpleNamespace(code="k7q2mx", items=[i.model_dump() for i in payload.items])

    async def no_db():
        yield None

    from app.db.engine import get_db
    from app.main import app
    monkeypatch.setattr(bag_routes.bag_service, "save", fake_save)
    app.dependency_overrides[get_db] = no_db
    bag_routes._recent.clear()
    yield
    app.dependency_overrides.pop(get_db, None)
    bag_routes._recent.clear()


def test_saving_needs_the_same_site_header_and_is_limited(client, saving):
    body = {"items": [{"name": "Headlamp", "slug": "headlamp"}]}
    assert client.post("/api/bags", json=body).status_code == 403
    first = client.post("/api/bags", json=body, headers={"X-Requested-With": "trekxp"})
    assert first.status_code == 201 and first.json() == {"code": "k7q2mx", "url": "/bag/k7q2mx", "count": 1}
    codes = [client.post("/api/bags", json=body, headers={"X-Requested-With": "trekxp"}).status_code
             for _ in range(bag_routes.SAVES_PER_HOUR)]
    assert codes[-1] == 429


def test_a_malformed_code_is_a_not_found_page(client):
    assert client.get("/bag/NOT-A-CODE").status_code == 404


# ---------- availability for the bag sidebar ----------


def gadget(gid, name, slug, *stock, price=1000):
    variants = [SimpleNamespace(id=gid * 10 + n, stock_quantity=q, price=price + n * 100, currency="BDT")
                for n, q in enumerate(stock)]
    return SimpleNamespace(id=gid, name=name, slug=slug, variants=variants)


def test_available_means_any_option_on_the_compare_page_is_in_stock():
    headlamp = gadget(1, "Headlamp", "headlamp", 0, 4, 0)
    led = gadget(2, "LED Headlamp", "led-headlamp", 2)            # the same item, by name
    towel = gadget(3, "Quick-Dry Towel", "quick-dry-towel", 0, 0)
    bare = gadget(4, "Sun Hat", "sun-hat")

    found = svc.availability([headlamp, led, towel, bare])

    assert found["headlamp"] == {"options": 4, "in_stock": 2, "in_stock_ids": [11, 20],
                                 "from_price": 1000, "currency": "BDT"}
    assert found["quick-dry-towel"]["in_stock"] == 0 and found["quick-dry-towel"]["from_price"] is None
    assert found["sun-hat"]["options"] == 0


def test_the_endpoint_answers_only_for_known_slugs(client, monkeypatch):
    async def everything():
        return {"headlamp": {"options": 3, "in_stock": 1, "in_stock_ids": [8], "from_price": 1300, "currency": "BDT"}}

    monkeypatch.setattr(bag_routes, "_load_availability", everything)
    body = client.get("/api/bag/availability?slugs=headlamp,unknown,../etc,HEADLAMP").json()
    assert body == {"headlamp": {"options": 3, "in_stock": 1, "in_stock_ids": [8], "from_price": 1300, "currency": "BDT"}}
    assert client.get("/api/bag/availability").json() == {}
