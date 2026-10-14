"""Admin CRUD for the catalog taxonomy, against a real database."""

from tests.db.conftest import CSRF


def test_trip_types_seed_and_can_be_added_and_hidden(admin):
    seeded = {o["value"] for o in admin.get("/api/admin/options/trip-types").json()}
    assert {"hiking", "beach", "winter_sports"} <= seeded

    created = admin.post(
        "/api/admin/options/trip-types", json={"label": "Pilgrimage"}, headers=CSRF
    ).json()
    assert created["value"] == "pilgrimage" and created["is_active"] is True

    # Adding the same label again reactivates rather than duplicating.
    again = admin.post(
        "/api/admin/options/trip-types", json={"label": "Pilgrimage"}, headers=CSRF
    ).json()
    assert again["id"] == created["id"]

    # Hiding it is a soft toggle, visible in the admin list.
    admin.patch(
        f"/api/admin/options/trip-types/{created['id']}",
        json={"is_active": False}, headers=CSRF,
    )
    rows = {o["value"]: o["is_active"] for o in admin.get("/api/admin/options/trip-types").json()}
    assert rows["pilgrimage"] is False


def test_divisions_seed_and_add(admin):
    names = {d["name"] for d in admin.get("/api/admin/divisions").json()}
    assert {"Dhaka", "Chattogram", "Sylhet"} <= names

    created = admin.post("/api/admin/divisions", json={"name": "Test Region"}, headers=CSRF)
    assert created.status_code == 201
    assert created.json()["name"] == "Test Region"


def test_add_a_destination_and_it_appears_in_the_picker(admin):
    created = admin.post(
        "/api/admin/destinations",
        json={"name": "Nikli Haor", "latitude": 24.31, "longitude": 90.95, "division": "Dhaka"},
        headers=CSRF,
    )
    assert created.status_code == 201

    rows = admin.get("/api/admin/destinations").json()
    assert "Nikli Haor" in [r["name"] for r in rows]


def test_an_unknown_trip_type_on_a_placement_is_rejected(admin):
    gadget = admin.post(
        "/api/coordinator/gadgets", json={"name": "Test Gadget"}, headers=CSRF
    ).json()

    response = admin.post(
        f"/api/coordinator/gadgets/{gadget['id']}/placements",
        json={
            "place": {"name": "Somewhere", "country_code": "BD", "country_name": "Bangladesh",
                      "latitude": 23.0, "longitude": 90.0},
            "trip_types": ["space_tourism"], "why": "Testing an unknown trip type.",
        },
        headers=CSRF,
    )
    assert response.status_code == 422
    assert "space_tourism" in response.json()["detail"]
