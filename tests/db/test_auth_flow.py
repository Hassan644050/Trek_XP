from fastapi.testclient import TestClient

from app.db.models import Role
from app.main import app
from tests.db.conftest import CSRF, PASSWORD, make_user, signed_in


def login(client, email, password):
    return client.post("/api/auth/login", json={"email": email, "password": password}, headers=CSRF)


def test_sign_in_sets_a_protected_cookie_and_me_works(db_app):
    make_user("rumi@trekxp.test", name="Rumi")
    client = TestClient(app)

    response = login(client, "  RUMI@trekxp.test ", PASSWORD)

    assert response.status_code == 200
    assert response.json()["email"] == "rumi@trekxp.test"
    assert "password_hash" not in response.json()

    cookie = response.headers["set-cookie"].lower()
    assert "trekxp_session=" in cookie
    assert "httponly" in cookie
    assert "samesite=strict" in cookie

    assert client.get("/api/auth/me").json()["name"] == "Rumi"


def test_wrong_password_and_unknown_email_look_identical(db_app):
    make_user("rumi@trekxp.test")
    client = TestClient(app)

    wrong = login(client, "rumi@trekxp.test", "not the password")
    unknown = login(client, "nobody@trekxp.test", PASSWORD)

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"detail": "Invalid email or password."}


def test_repeated_failures_lock_the_account(db_app):
    # MAX_FAILED_LOGINS is 3 in these tests.
    make_user("rumi@trekxp.test")
    client = TestClient(app)

    for _ in range(3):
        assert login(client, "rumi@trekxp.test", "guess guess guess").status_code == 401

    locked = login(client, "rumi@trekxp.test", PASSWORD)

    # Even the right password is refused until the lock expires.
    assert locked.status_code == 429
    assert "Try again later" in locked.json()["detail"]


def test_sign_out_kills_the_session_server_side(db_app):
    make_user("rumi@trekxp.test")
    client = signed_in("rumi@trekxp.test")
    stolen_cookie = client.cookies.get("trekxp_session")

    assert client.post("/api/auth/logout", headers=CSRF).status_code == 204

    # Replaying the old cookie must not work: the session was revoked.
    replay = TestClient(app, cookies={"trekxp_session": stolen_cookie})
    assert replay.get("/api/auth/me").status_code == 401


def test_deactivated_account_cannot_sign_in(db_app):
    make_user("gone@trekxp.test", active=False)
    assert login(TestClient(app), "gone@trekxp.test", PASSWORD).status_code == 401


def test_forged_cookie_is_rejected(db_app):
    forged = TestClient(app, cookies={"trekxp_session": "made-up-token"})
    assert forged.get("/api/auth/me").status_code == 401


def test_coordinator_cannot_reach_admin_endpoints(coordinator):
    response = coordinator.get("/api/admin/users")
    assert response.status_code == 403
    assert response.json() == {"detail": "Admin access required."}


def test_admin_can_do_coordinator_work(admin):
    assert admin.get("/api/coordinator/gadgets").status_code == 200


def test_signed_in_write_without_header_is_still_refused(coordinator):
    response = coordinator.post("/api/coordinator/gadgets", json={"name": "Dry bag"})
    assert response.status_code == 403


def test_admin_role_is_reported(admin):
    assert admin.get("/api/auth/me").json()["role"] == Role.ADMIN.value
