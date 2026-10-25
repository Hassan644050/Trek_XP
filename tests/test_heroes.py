"""Hero photo helpers: slugs, renditions, keys and the public-read cache."""

import io

import pytest
from PIL import Image

from app.services.heroes import hero_slug
from app.services.media.images import process_image
from app.services.media.storage import all_keys, is_valid_key, new_image_key
from app.services.media.variants import HERO_FULL, HERO_SMALL, HERO_VARIANT_NAMES, HERO_VARIANTS


def photo(size) -> bytes:
    out = io.BytesIO()
    Image.linear_gradient("L").resize(size).convert("RGB").save(out, "JPEG")
    return out.getvalue()


def decode(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    image.load()
    return image


@pytest.mark.parametrize("name,slug", [
    ("Cox's Bazar", "coxs-bazar"),       # same scheme as ?to= on the home page
    ("Bholaganj Sada Pathor", "bholaganj-sada-pathor"),
    ("", ""),                            # blank = the country's default hero
    ("   ", ""),
    (None, ""),
])
def test_hero_slug(name, slug):
    assert hero_slug(name) == slug


def test_hero_renditions_are_wide_and_bounded():
    renditions = process_image(photo((3600, 1500)), HERO_VARIANTS)

    assert set(renditions) == set(HERO_VARIANT_NAMES)
    assert decode(renditions[HERO_FULL.name]).size == (2400, 1000)
    assert decode(renditions[HERO_SMALL.name]).size == (1080, 450)


def test_hero_size_limit_is_its_own():
    data = photo((800, 400))
    with pytest.raises(Exception, match="1 MB"):
        process_image(data + b"\0" * (1024 * 1024), HERO_VARIANTS, max_bytes=1024 * 1024)


def test_hero_keys_live_in_their_own_folder():
    key = new_image_key("heroes")

    assert key.startswith("heroes/")
    assert all(is_valid_key(k) for k in all_keys(key, HERO_VARIANT_NAMES))
    with pytest.raises(ValueError):
        new_image_key("../elsewhere")


def test_an_unserved_country_gets_no_heroes():
    from fastapi.testclient import TestClient

    from app.main import app

    response = TestClient(app).get("/heroes?country=XY")

    assert response.status_code == 200 and response.json() == []
