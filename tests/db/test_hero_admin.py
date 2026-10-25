"""Home page hero photos: admin upload, replace, delete, and the public read."""

import io

from PIL import Image

from tests.db.conftest import CSRF


def jpeg(color="orange", size=(1600, 700)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, "JPEG")
    return out.getvalue()


def upload(client, data, alt="A wide beach at sunset", place=""):
    return client.put(
        "/api/admin/heroes",
        files={"file": ("hero.jpg", data, "image/jpeg")},
        data={"alt": alt, "place": place},
        headers=CSRF,
    )


def stored(storage) -> set[str]:
    return {p.name for p in (storage.directory / "heroes").glob("*.webp")}


def test_default_and_destination_heroes_are_public(admin, db_app):
    default = upload(admin, jpeg()).json()
    jaflong = upload(admin, jpeg("teal"), alt="River at Jaflong", place="Jaflong").json()

    assert default["place_slug"] == "" and default["place_name"] is None
    assert jaflong["place_slug"] == "jaflong"
    assert jaflong["small_url"].endswith("_small.webp")

    public = admin.get("/heroes").json()
    # The default sorts first, so the home page can read it without searching.
    assert [h["place_slug"] for h in public] == ["", "jaflong"]
    assert len(stored(db_app)) == 4  # two renditions each


def test_uploading_again_for_a_place_replaces_its_photo(admin, db_app):
    first = upload(admin, jpeg(), place="Cox's Bazar").json()
    second = upload(admin, jpeg("blue"), alt="Another view", place="Cox's Bazar").json()

    assert second["id"] == first["id"]
    assert second["place_slug"] == "coxs-bazar"
    assert second["image_url"] != first["image_url"]
    # The old renditions are gone; only the new pair remains.
    assert len(stored(db_app)) == 2


def test_the_public_list_sees_changes_straight_away(admin):
    assert admin.get("/heroes").json() == []  # now cached as empty

    hero = upload(admin, jpeg()).json()
    assert [h["id"] for h in admin.get("/heroes").json()] == [hero["id"]]

    admin.delete(f"/api/admin/heroes/{hero['id']}", headers=CSRF)
    assert admin.get("/heroes").json() == []


def test_delete_removes_the_row_and_the_files(admin, db_app):
    hero = upload(admin, jpeg()).json()

    assert admin.delete(f"/api/admin/heroes/{hero['id']}", headers=CSRF).status_code == 204
    assert admin.get("/api/admin/heroes").json() == []
    assert stored(db_app) == set()


def test_a_bad_file_or_missing_description_is_refused(admin, db_app):
    assert upload(admin, b"not an image").status_code == 422
    assert upload(admin, jpeg(), alt="  ").status_code == 422
    assert stored(db_app) == set()


def test_coordinators_cannot_manage_heroes(coordinator):
    assert upload(coordinator, jpeg()).status_code == 403
    assert coordinator.get("/api/admin/heroes").status_code == 403
