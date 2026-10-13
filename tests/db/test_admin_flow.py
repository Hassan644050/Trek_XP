from fastapi.testclient import TestClient

from app.main import app
from tests.db.conftest import CSRF, signed_in


NEW_USER = {"name": "Nabila", "email": "Nabila@TrekXP.test", "password": "a long temp password"}


def create(admin, **overrides):
    return admin.post("/api/admin/users", json={**NEW_USER, **overrides}, headers=CSRF)


def test_admin_creates_a_coordinator_who_can_sign_in(admin):
    response = create(admin)

    assert response.status_code == 201
    assert (response.json()["email"], response.json()["role"]) == ("nabila@trekxp.test", "coordinator")

    coordinator = signed_in("nabila@trekxp.test", NEW_USER["password"])
    assert coordinator.get("/api/coordinator/gadgets").status_code == 200


def test_duplicate_email_is_rejected(admin):
    create(admin)
    assert create(admin, email="NABILA@trekxp.test").status_code == 409


def test_weak_password_is_rejected_with_a_reason(admin):
    response = create(admin, password="short")

    assert response.status_code == 422
    assert "at least 10" in response.json()["detail"]


def test_deactivation_signs_the_user_out_immediately(admin):
    user_id = create(admin).json()["id"]
    coordinator = signed_in("nabila@trekxp.test", NEW_USER["password"])

    admin.patch(f"/api/admin/users/{user_id}", json={"is_active": False}, headers=CSRF)

    assert coordinator.get("/api/coordinator/gadgets").status_code == 401


def test_password_reset_signs_out_and_new_password_works(admin):
    user_id = create(admin).json()["id"]
    old_session = signed_in("nabila@trekxp.test", NEW_USER["password"])

    response = admin.patch(f"/api/admin/users/{user_id}", json={"password": "a brand new password"}, headers=CSRF)

    assert response.status_code == 200
    assert old_session.get("/api/auth/me").status_code == 401
    signed_in("nabila@trekxp.test", "a brand new password")


def test_admin_cannot_lock_themself_out(admin):
    my_id = admin.get("/api/auth/me").json()["id"]

    for change in ({"is_active": False}, {"role": "coordinator"}):
        response = admin.patch(f"/api/admin/users/{my_id}", json=change, headers=CSRF)
        assert response.status_code == 403


def test_promoted_coordinator_gains_admin_access(admin):
    user_id = create(admin).json()["id"]
    admin.patch(f"/api/admin/users/{user_id}", json={"role": "admin"}, headers=CSRF)

    promoted = signed_in("nabila@trekxp.test", NEW_USER["password"])
    assert promoted.get("/api/admin/users").status_code == 200


def test_user_list_never_exposes_password_hashes(admin):
    create(admin)
    users = admin.get("/api/admin/users").json()

    assert len(users) == 2
    assert all("password" not in key for user in users for key in user)


def test_signed_out_client_cannot_create_users(db_app):
    assert TestClient(app).post("/api/admin/users", json=NEW_USER, headers=CSRF).status_code == 401
