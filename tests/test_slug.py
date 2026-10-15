import pytest

from app.services.slug import url_slug


@pytest.mark.parametrize("name,expected", [
    ("Waterproof Dry Bag", "waterproof-dry-bag"),
    ("Cox's Bazar Kit", "coxs-bazar-kit"),
    ("Quick-Dry Towel", "quick-dry-towel"),
    ("  Power   Bank  ", "power-bank"),
    ("Café Press!", "caf-press"),
    ("日本", ""),
])
def test_url_slug(name, expected):
    assert url_slug(name) == expected


def test_url_slug_is_capped():
    assert len(url_slug("x " * 200)) <= 120
