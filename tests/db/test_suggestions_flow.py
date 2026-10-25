"""Model suggestions against a real database: saving, de-duplicating,
guard rails, and coordinator review."""

import asyncio

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.recommendation import Priority, Recommendation
from app.services.gadgets.suggestions import SuggestionBatch, save_suggestions
from tests.db.conftest import CSRF, _engine


def rec(name, why="Useful on this trip.", priority=Priority.RECOMMENDED, category=None):
    return Recommendation(gadget=name, why=why, priority=priority, category=category)


def save(*recs, place="Cox's Bazar", trip_type="beach"):
    async def go():
        engine = _engine()
        try:
            batch = SuggestionBatch(place_name=place, country_code="BD", trip_type=trip_type, suggestions=list(recs))
            return await save_suggestions(async_sessionmaker(engine, expire_on_commit=False), batch)
        finally:
            await engine.dispose()

    return asyncio.run(go())


def pending(client):
    return client.get("/api/coordinator/gadgets?status=pending").json()


def test_a_new_suggestion_is_saved_inactive_and_pending(coordinator):
    created = save(rec("Portable Bluetooth Speaker", "Music on beach evenings.", Priority.OPTIONAL, "Audio"))
    assert len(created) == 1

    (g,) = pending(coordinator)
    assert (g["name"], g["is_active"], g["origin"], g["review_status"], g["suggestion_count"]) == \
        ("Portable Bluetooth Speaker", False, "model", "pending", 1)

    detail = coordinator.get(f"/api/coordinator/gadgets/{g['id']}").json()
    (p,) = detail["placements"]
    assert (p["place"]["name"], p["trip_types"], p["priority"], p["why"]) == \
        ("Cox's Bazar", ["beach"], "optional", "Music on beach evenings.")

    # Not public until approved.
    assert coordinator.get("/gadget/portable-bluetooth-speaker").status_code == 404


def test_repeats_and_loose_duplicates_add_to_the_count(coordinator):
    save(rec("Portable Bluetooth Speaker"))
    assert save(rec("Bluetooth Speaker")) == []           # loose duplicate
    save(rec("portable bluetooth speaker"), place="Saint Martin's Island")

    (g,) = pending(coordinator)
    assert g["suggestion_count"] == 3
    assert g["placement_count"] == 2                       # one per destination


def test_coordinator_gadgets_are_never_touched(coordinator):
    mine = coordinator.post("/api/coordinator/gadgets", json={"name": "Dry Bag"}, headers=CSRF).json()

    assert save(rec("Waterproof Dry Bag")) == []
    after = coordinator.get(f"/api/coordinator/gadgets/{mine['id']}").json()
    assert after["placements"] == [] and after["origin"] == "coordinator"


def test_unknown_places_and_trip_types_are_refused(coordinator):
    assert save(rec("Trident"), place="Atlantis") == []
    assert save(rec("Trident"), trip_type="space_tourism") == []
    assert pending(coordinator) == []


def test_approve_publishes_and_reject_retires(coordinator):
    save(rec("Portable Bluetooth Speaker"), rec("Hammock"))
    speaker, hammock = sorted(pending(coordinator), key=lambda g: g["name"], reverse=True)

    approved = coordinator.post(f"/api/coordinator/gadgets/{speaker['id']}/review",
                                json={"action": "approve"}, headers=CSRF).json()
    assert (approved["is_active"], approved["review_status"]) == (True, "approved")
    assert coordinator.get("/gadget/portable-bluetooth-speaker").status_code == 200

    rejected = coordinator.post(f"/api/coordinator/gadgets/{hammock['id']}/review",
                                json={"action": "reject"}, headers=CSRF).json()
    assert (rejected["is_active"], rejected["review_status"]) == (False, "rejected")

    assert pending(coordinator) == []
    assert [g["name"] for g in coordinator.get("/api/coordinator/gadgets?status=rejected").json()] == ["Hammock"]

    # A rejected item is not revived by a later suggestion.
    save(rec("Hammock"))
    assert pending(coordinator) == []


def test_switching_a_suggestion_on_in_the_editor_approves_it(coordinator):
    save(rec("Hammock"))
    (g,) = pending(coordinator)

    body = coordinator.patch(f"/api/coordinator/gadgets/{g['id']}", json={"is_active": True}, headers=CSRF).json()
    assert body["review_status"] == "approved"


def test_only_model_suggestions_can_be_reviewed(coordinator):
    mine = coordinator.post("/api/coordinator/gadgets", json={"name": "Dry Bag"}, headers=CSRF).json()
    response = coordinator.post(f"/api/coordinator/gadgets/{mine['id']}/review",
                                json={"action": "approve"}, headers=CSRF)
    assert response.status_code == 422
