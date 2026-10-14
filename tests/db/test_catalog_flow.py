import io

from PIL import Image
from sqlalchemy import func, select

from app.db.models import Place
from app.exceptions.exceptions import ImageStorageException
from app.services.destination.geocode_types import GeoResult
from tests.db.conftest import CSRF, run


KAPTAI = {"name": "Kaptai Lake", "country_code": "BD", "country_name": "Bangladesh",
          "latitude": 22.76, "longitude": 92.276}
SYLHET = {"name": "Sylhet", "country_code": "BD", "country_name": "Bangladesh",
          "latitude": 24.899, "longitude": 91.872}


def jpeg(color="orange", size=(800, 600)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, "JPEG")
    return out.getvalue()


def new_gadget(client, name="Waterproof dry bag", **extra):
    response = client.post("/api/coordinator/gadgets", json={"name": name, **extra}, headers=CSRF)
    assert response.status_code == 201, response.text
    return response.json()


def add_placement(client, gadget_id, place=KAPTAI, **overrides):
    body = {"place": place, "trip_types": ["backpacking"], "activities": ["photography"],
            "priority": "essential", "why": "Boat rides splash phones and cameras."}
    body.update(overrides)
    return client.post(f"/api/coordinator/gadgets/{gadget_id}/placements", json=body, headers=CSRF)


def count_places() -> int:
    async def q(session):
        return await session.scalar(select(func.count()).select_from(Place))
    return run(q)


# ---------- gadgets ----------


def test_create_and_read_gadget(coordinator):
    g = new_gadget(coordinator, category="Protection", description="Keeps electronics dry.")

    assert (g["name"], g["category"], g["placement_count"], g["image_url"]) == (
        "Waterproof dry bag", "Protection", 0, None)
    assert coordinator.get(f"/api/coordinator/gadgets/{g['id']}").json()["placements"] == []


def test_gadget_names_are_unique_ignoring_case(coordinator):
    new_gadget(coordinator, "Power bank")

    response = coordinator.post("/api/coordinator/gadgets", json={"name": "POWER   bank"}, headers=CSRF)

    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]


def test_search_and_rename(coordinator):
    a = new_gadget(coordinator, "Power bank")
    new_gadget(coordinator, "Headlamp")

    found = coordinator.get("/api/coordinator/gadgets?q=power").json()
    assert [g["name"] for g in found] == ["Power bank"]

    # Wildcards are literal: "%" must not match everything.
    assert coordinator.get("/api/coordinator/gadgets?q=%25").json() == []

    renamed = coordinator.patch(f"/api/coordinator/gadgets/{a['id']}",
                                json={"name": "20,000mAh power bank"}, headers=CSRF)
    assert renamed.json()["name"] == "20,000mAh power bank"

    clash = coordinator.patch(f"/api/coordinator/gadgets/{a['id']}", json={"name": "headlamp"}, headers=CSRF)
    assert clash.status_code == 409


def test_missing_gadget_is_404(coordinator):
    assert coordinator.get("/api/coordinator/gadgets/999").status_code == 404


# ---------- placements ----------


def test_placement_round_trip(coordinator):
    g = new_gadget(coordinator)

    response = add_placement(coordinator, g["id"])
    assert response.status_code == 201
    [p] = response.json()["placements"]
    assert p["place"]["name"] == "Kaptai Lake"
    assert (p["trip_types"], p["activities"], p["priority"]) == (["backpacking"], ["photography"], "essential")

    updated = coordinator.patch(f"/api/coordinator/placements/{p['id']}",
                                json={"activities": [], "priority": "recommended"}, headers=CSRF).json()
    [p2] = updated["placements"]
    assert (p2["activities"], p2["priority"]) == ([], "recommended")

    after_delete = coordinator.delete(f"/api/coordinator/placements/{p['id']}", headers=CSRF).json()
    assert after_delete["placements"] == []


def test_same_place_is_stored_once(coordinator):
    a = new_gadget(coordinator, "Dry bag")
    b = new_gadget(coordinator, "Headlamp")

    add_placement(coordinator, a["id"])
    add_placement(coordinator, b["id"])
    add_placement(coordinator, b["id"], place=SYLHET)

    assert count_places() == 2


def test_placement_needs_a_trip_type(coordinator):
    g = new_gadget(coordinator)
    assert add_placement(coordinator, g["id"], trip_types=[]).status_code == 422


def test_saved_places_are_searchable(coordinator):
    add_placement(coordinator, new_gadget(coordinator)["id"])

    names = [p["name"] for p in coordinator.get("/api/coordinator/places?q=kapt").json()]
    assert names == ["Kaptai Lake"]


def test_lookup_uses_the_full_geocoder(coordinator, monkeypatch):
    async def fake_geocode(destination, home_country=None):
        assert destination == "Kaptai Lake"
        return GeoResult(name="Kaptai Lake", latitude=22.76, longitude=92.276,
                         country="Bangladesh", country_code="BD", timezone=None, source="openstreetmap")

    monkeypatch.setattr("app.routes.coordinator.geocode", fake_geocode)

    found = coordinator.get("/api/coordinator/places/lookup?q=Kaptai%20Lake").json()
    assert (found["name"], found["country_code"]) == ("Kaptai Lake", "BD")


def test_deleting_a_gadget_removes_its_placements(coordinator):
    g = new_gadget(coordinator)
    add_placement(coordinator, g["id"])

    assert coordinator.delete(f"/api/coordinator/gadgets/{g['id']}", headers=CSRF).status_code == 204
    assert coordinator.get(f"/api/coordinator/gadgets/{g['id']}").status_code == 404
    # The place stays: other gadgets may still use it.
    assert count_places() == 1


# ---------- images ----------


def upload(client, gadget_id, data, filename="photo.jpg"):
    return client.put(f"/api/coordinator/gadgets/{gadget_id}/image",
                      files={"file": (filename, data, "image/jpeg")}, headers=CSRF)


def test_image_upload_replace_and_remove(coordinator, db_app):
    storage = db_app
    g = new_gadget(coordinator)

    first = upload(coordinator, g["id"], jpeg("orange")).json()
    first_key = first["image_url"].removeprefix("/media/")
    assert first["image_url"].endswith(".webp")
    assert (storage.directory / first_key).exists()

    second = upload(coordinator, g["id"], jpeg("blue")).json()
    second_key = second["image_url"].removeprefix("/media/")
    assert second_key != first_key
    assert not (storage.directory / first_key).exists()  # old file cleaned up

    removed = coordinator.delete(f"/api/coordinator/gadgets/{g['id']}/image", headers=CSRF).json()
    assert removed["image_url"] is None
    assert not (storage.directory / second_key).exists()


def test_bad_upload_leaves_the_existing_image_alone(coordinator):
    g = new_gadget(coordinator)
    good = upload(coordinator, g["id"], jpeg()).json()["image_url"]

    response = upload(coordinator, g["id"], b"%PDF-1.7 definitely not a photo", "photo.jpg")

    assert response.status_code == 422
    assert coordinator.get(f"/api/coordinator/gadgets/{g['id']}").json()["image_url"] == good


def test_a_failed_cleanup_does_not_fail_an_upload_that_worked(coordinator, db_app, monkeypatch):
    """The new image is stored and committed; only tidying up the old one
    failed. Reporting an error here would be a lie, and R2 deletes are a
    network call that can fail on their own."""
    g = new_gadget(coordinator)
    first = upload(coordinator, g["id"], jpeg("orange")).json()["image_url"]

    def refuse(key):
        raise ImageStorageException("R2 is having a bad day")

    monkeypatch.setattr(db_app, "delete", refuse)

    second = upload(coordinator, g["id"], jpeg("blue"))

    assert second.status_code == 200
    assert second.json()["image_url"] != first
    key = second.json()["image_url"].removeprefix("/media/")
    assert (db_app.directory / key).exists()


def test_a_failed_upload_is_a_503_and_keeps_the_old_image(coordinator, db_app, monkeypatch):
    g = new_gadget(coordinator)
    good = upload(coordinator, g["id"], jpeg()).json()["image_url"]

    def refuse(key, data):
        raise ImageStorageException("The image could not be stored just now.")

    monkeypatch.setattr(db_app, "save", refuse)

    response = upload(coordinator, g["id"], jpeg("blue"))

    assert response.status_code == 503
    # Nothing was committed, so the gadget still points at the old image.
    assert coordinator.get(f"/api/coordinator/gadgets/{g['id']}").json()["image_url"] == good


def test_deleting_a_gadget_deletes_its_image_file(coordinator, db_app):
    g = new_gadget(coordinator)
    key = upload(coordinator, g["id"], jpeg()).json()["image_url"].removeprefix("/media/")

    coordinator.delete(f"/api/coordinator/gadgets/{g['id']}", headers=CSRF)

    assert not (db_app.directory / key).exists()


# ---------- places the geocoders do not know ----------


def test_coordinator_can_add_an_unmapped_place_by_district(coordinator):
    """Sada Pathor is in no gazetteer, so the district supplies its location."""
    response = coordinator.post(
        "/api/coordinator/places/manual",
        json={"name": "  Bholaganj   Sada Pathor ", "district": "Sylhet"},
        headers=CSRF,
    )

    assert response.status_code == 200
    place = response.json()
    assert place["name"] == "Bholaganj Sada Pathor"
    assert (place["district"], place["division"]) == ("Sylhet", "Sylhet")
    assert (place["country_code"], place["country_name"]) == ("BD", "Bangladesh")
    # Anchored to the district, not left at 0,0.
    assert 24.0 < place["latitude"] < 25.5
    assert 91.0 < place["longitude"] < 92.5


def test_manual_place_can_be_used_in_a_placement_and_is_saved(coordinator):
    place = coordinator.post(
        "/api/coordinator/places/manual",
        json={"name": "Bichanakandi", "district": "Sylhet"},
        headers=CSRF,
    ).json()

    g = new_gadget(coordinator, "Dry bag")
    created = add_placement(coordinator, g["id"], place=place)

    assert created.status_code == 201
    [p] = created.json()["placements"]
    # The district must survive the whole round trip into the database,
    # not just be echoed by the manual-place endpoint.
    assert (p["place"]["name"], p["place"]["district"], p["place"]["division"]) == (
        "Bichanakandi", "Sylhet", "Sylhet",
    )

    # Saved, so the next coordinator finds it without re-entering anything.
    assert [s["name"] for s in coordinator.get("/api/coordinator/places?q=bichana").json()] == [
        "Bichanakandi"
    ]


def test_old_district_spellings_are_accepted(coordinator):
    place = coordinator.post(
        "/api/coordinator/places/manual",
        json={"name": "Foy's Lake", "district": "Chittagong"},
        headers=CSRF,
    ).json()

    assert place["district"] == "Chattogram"


def test_unknown_district_is_refused(coordinator):
    response = coordinator.post(
        "/api/coordinator/places/manual",
        json={"name": "Somewhere", "district": "Atlantis"},
        headers=CSRF,
    )

    assert response.status_code == 404
    assert "not a district we know" in response.json()["detail"]


def test_same_name_in_two_districts_stays_separate(coordinator):
    """Companiganj exists in both Sylhet and Noakhali; they must not merge."""
    sylhet = coordinator.post("/api/coordinator/places/manual",
                              json={"name": "Companiganj", "district": "Sylhet"}, headers=CSRF).json()
    noakhali = coordinator.post("/api/coordinator/places/manual",
                                json={"name": "Companiganj", "district": "Noakhali"}, headers=CSRF).json()

    assert (sylhet["latitude"], sylhet["longitude"]) != (noakhali["latitude"], noakhali["longitude"])

    g = new_gadget(coordinator, "Dry bag")
    add_placement(coordinator, g["id"], place=sylhet)
    add_placement(coordinator, g["id"], place=noakhali)

    assert count_places() == 2


def test_admin_areas_are_offered_to_the_form(coordinator):
    body = coordinator.get("/api/coordinator/admin-areas").json()

    assert len(body["divisions"]) == 8
    assert sum(len(d["districts"]) for d in body["divisions"]) == 64

    sylhet = next(d for d in body["divisions"] if d["name"] == "Sylhet")
    assert sylhet["districts"] == ["Habiganj", "Moulvibazar", "Sunamganj", "Sylhet"]


def test_manual_place_needs_signing_in(db_app):
    from fastapi.testclient import TestClient
    from app.main import app

    response = TestClient(app).post("/api/coordinator/places/manual",
                                    json={"name": "X", "district": "Sylhet"}, headers=CSRF)
    assert response.status_code == 401
