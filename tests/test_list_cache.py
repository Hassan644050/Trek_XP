"""Faster lists: the model-list cache, the quick answer, and descriptions
asked for in the list's own model call."""

from datetime import date

from app.models.context import ClimateInfo, TripContext
from app.models.recommendation import Origin, Recommendation
from app.models.trip import TripRequest
from app.services import analytics
from app.services.gadgets.catalog import CatalogMatch
from app.services.gadgets.list_cache import cache_key
from app.services.gadgets.llm_source import parse_recommendations
from app.services.gadgets.prompt import build_gadget_prompt
from tests.conftest import FakeGadgetSource


def key_for(**overrides):
    fields = dict(destination="Jaflong", start_date=date(2026, 11, 10), end_date=date(2026, 11, 14),
                  trip_types=["hiking"], activities=["photography"], travelers=2)
    fields.update(overrides)
    return cache_key(TripContext(trip=TripRequest(**fields), resolved_place=fields["destination"],
                                 novel_item_count=5))


# ---------- the key ----------


def test_near_identical_trips_share_a_key():
    base = key_for()
    # Other dates in the same month, same length bucket; order of choices.
    assert key_for(start_date=date(2026, 11, 20), end_date=date(2026, 11, 23)) == base
    assert key_for(trip_types=["hiking"], activities=["photography"], travelers=3) == base


def test_what_changes_the_answer_changes_the_key():
    base = key_for()
    assert key_for(destination="Sajek Valley") != base
    assert key_for(start_date=date(2026, 6, 10), end_date=date(2026, 6, 14)) != base   # season
    assert key_for(trip_types=["hiking", "camping_trip"]) != base
    assert key_for(activities=[]) != base
    assert key_for(gender="female") != base
    assert key_for(end_date=date(2026, 11, 30)) != base                                 # 21 days


def test_a_routes_order_does_not_matter():
    stops = [{"name": "Cox's Bazar"}, {"name": "Bandarban"}]
    def route_key(order):
        trip = TripRequest(stops=order, start_date=date(2026, 12, 1), end_date=date(2026, 12, 6),
                           trip_types=["beach"])
        from app.models.context import StopContext
        ctx = TripContext(trip=trip, stops=[StopContext(name=s["name"], latitude=0, longitude=0) for s in order])
        return cache_key(ctx)
    assert route_key(stops) == route_key(stops[::-1])


# ---------- one model call per list ----------


def test_the_prompt_asks_for_a_description_and_the_reply_keeps_it():
    ctx = TripContext(trip=TripRequest(destination="Jaflong", start_date=date(2026, 11, 10),
                                       end_date=date(2026, 11, 14), trip_type="hiking"))
    assert '"description"' in build_gadget_prompt(ctx)

    recs = parse_recommendations('[{"gadget": "Headlamp", "why": "Dark trails.", '
                                 '"description": "A hands-free torch; look for 200+ lumens."}]')
    assert recs[0].description == "A hands-free torch; look for 200+ lumens."


# ---------- the route ----------


def use_climate(monkeypatch):
    async def fake(**kwargs):
        return ClimateInfo(summary="Mild.", historical=True)
    monkeypatch.setattr("app.services.destination.aggregator.fetch_climate", fake)


def use_catalog(monkeypatch, *names):
    recs = [Recommendation(gadget=n, why="On file.", origin=Origin.COMMUNITY, verified=True) for n in names]
    async def fake(context):
        return CatalogMatch(recommendations=recs, existing_names=list(names))
    monkeypatch.setattr("app.routes.recommend._load_catalog", fake)


def test_quick_answer_skips_the_model_and_is_not_counted(client, monkeypatch, trip_payload):
    use_climate(monkeypatch)
    use_catalog(monkeypatch, "Dry Bag")
    source = FakeGadgetSource(recommendations=[Recommendation(gadget="Headlamp", why="x")])
    monkeypatch.setattr("app.routes.recommend.get_gadget_source", lambda: source)

    body = client.post("/recommend?quick=1", json=trip_payload).json()

    assert source.contexts == []                       # no model call
    assert body["pending"] is True
    assert [r["gadget"] for r in body["recommendations"]] == ["Dry Bag"]
    assert analytics._buffer.counts == {}              # the full request counts it


def test_a_cache_hit_skips_the_model_and_drops_items_now_in_the_catalog(client, monkeypatch, trip_payload):
    use_climate(monkeypatch)
    use_catalog(monkeypatch, "Headlamp")               # a coordinator added it since
    source = FakeGadgetSource(error=RuntimeError("model must not be called"))
    monkeypatch.setattr("app.routes.recommend.get_gadget_source", lambda: source)
    cached = [Recommendation(gadget="Headlamp", why="x"), Recommendation(gadget="Leech Socks", why="y")]

    async def hit(key, **kwargs):
        return cached
    monkeypatch.setattr("app.routes.recommend._cached_items", hit)
    saved = []
    monkeypatch.setattr("app.routes.recommend._schedule_suggestions", lambda *a: saved.append(a))

    for url in ("/recommend", "/recommend?quick=1"):
        body = client.post(url, json=trip_payload).json()
        assert [r["gadget"] for r in body["recommendations"]] == ["Headlamp", "Leech Socks"]
        assert body["pending"] is False
        assert "cached_recommendations" in body["sources"]
        assert "llm_gadget_knowledge" not in body["sources"]
    assert saved == []                                 # saved for review the first time


def test_a_miss_remembers_the_models_items(client, monkeypatch, trip_payload, fake_source):
    use_climate(monkeypatch)
    monkeypatch.setattr("app.routes.recommend.get_gadget_source", lambda: fake_source)
    remembered = []

    async def remember(key, items):
        remembered.append((key, [i.gadget for i in items]))
    monkeypatch.setattr("app.routes.recommend._remember_items", remember)

    client.post("/recommend", json=trip_payload)

    assert len(remembered) == 1
    key, names = remembered[0]
    assert len(key) == 64 and names == ["Universal adapter (Type A/C/D/G/K)", "Headlamp"]
