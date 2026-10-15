"""The server-rendered gadget detail page: HTML, SEO tags, escaping."""

import json
import re
from types import SimpleNamespace

import pytest

from app.routes.gadget_pages import _not_found, _render_detail, _type_key


REQUEST = SimpleNamespace(base_url="https://trekxp.example/")


def placement(place_name, division, trip_types):
    return SimpleNamespace(
        place=SimpleNamespace(name=place_name, division=division),
        trip_types=trip_types,
    )


def variant(brand, quality, price, **over):
    base = dict(brand=brand, model_name=None, color=None, quality=quality,
                price=price, currency="BDT", vendor=None, url=None)
    base.update(over)
    return SimpleNamespace(**base)


def gadget(**over):
    base = dict(
        name="Waterproof Dry Bag", slug="waterproof-dry-bag", brand="Sea to Summit",
        model_name="Big River", category="Protection", color="Blue",
        description="Keeps your gear dry.", image_key=None,
        placements=[
            placement("Cox's Bazar", "Chattogram", ["beach"]),
            placement("Saint Martin's Island", "Chattogram", ["beach", "backpacking"]),
            placement("Cox's Bazar", "Chattogram", ["hiking"]),  # same place again
        ],
        variants=[],
    )
    base.update(over)
    return SimpleNamespace(**base)


def test_detail_has_title_canonical_and_description():
    html = _render_detail(REQUEST, gadget())

    assert "<title>Waterproof Dry Bag by Sea to Summit — Trek_XP</title>" in html
    assert '<link rel="canonical" href="https://trekxp.example/gadget/waterproof-dry-bag" />' in html
    assert 'name="description" content="Keeps your gear dry."' in html


def test_detail_has_valid_product_json_ld():
    html = _render_detail(REQUEST, gadget())
    block = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    data = json.loads(block.group(1))

    assert data["@type"] == "Product"
    assert data["name"] == "Waterproof Dry Bag"
    assert data["brand"] == {"@type": "Brand", "name": "Sea to Summit"}
    assert data["url"] == "https://trekxp.example/gadget/waterproof-dry-bag"


def test_detail_has_no_recommended_for_destination_section():
    html = _render_detail(REQUEST, gadget())
    assert "Recommended for" not in html
    assert 'href="/?to=' not in html


@pytest.mark.parametrize("name,expected", [
    ("Sun Hat", "hat"),
    ("Bucket Hat", "hat"),
    ("Water Shoes", "shoe"),
    ("Trekking Shoes", "shoe"),
    ("Waterproof Dry Bag", "bag"),
    ("Sunscreen (SPF 50)", "sunscreen"),
])
def test_type_key(name, expected):
    assert _type_key(name) == expected


def test_detail_escapes_user_content():
    html = _render_detail(REQUEST, gadget(name='Dry "Bag" <x>', description="<script>bad()</script>"))

    assert "<script>bad()</script>" not in html
    assert "&lt;script&gt;bad()&lt;/script&gt;" in html


def test_not_found_is_404_and_noindex():
    response = _not_found(REQUEST)

    assert response.status_code == 404
    assert 'name="robots" content="noindex"' in response.body.decode()


def other(name, slug, category="Protection"):
    return SimpleNamespace(
        name=name, slug=slug, category=category, brand=None, image_key=None)


def test_detail_offers_more_of_the_same_type():
    # gadget() is a "Waterproof Dry Bag" -> type "bag" -> "More Bags".
    similar = [other("Dry Bag", "dry-bag"), other("Compression Bag", "compression-bag")]
    html = _render_detail(REQUEST, gadget(), similar)

    assert "More Bags" in html
    assert "Similar gadgets" not in html
    assert 'href="/gadget/dry-bag"' in html
    assert 'href="/gadget/compression-bag"' in html


def test_detail_without_same_type_gadgets_omits_that_section():
    html = _render_detail(REQUEST, gadget(), [])
    assert "More Bags" not in html


def test_buying_options_render_sorted_by_quality_then_price():
    variants = [
        variant("Anker Prime", "premium", 6500, color="Graphite", vendor="Pickaboo"),
        variant("Generic", "budget", 1200, vendor="Local market"),
        variant("Anker Core", "standard", 2900, vendor="Daraz"),
    ]
    html = _render_detail(REQUEST, gadget(variants=variants))

    assert "Buying options" in html
    # Budget first, then standard, then premium (quality order).
    assert html.index("Generic") < html.index("Anker Core") < html.index("Anker Prime")
    assert "৳1,200" in html and "৳6,500" in html
    assert 'var-tier budget' in html and 'var-tier premium' in html


def test_a_variant_with_a_url_links_out_safely():
    v = variant("Anker", "standard", 2900, url="https://daraz.com.bd/x")
    html = _render_detail(REQUEST, gadget(variants=[v]))

    assert 'href="https://daraz.com.bd/x"' in html
    assert 'rel="noopener nofollow"' in html


def test_no_variants_means_no_buying_options_section():
    assert "Buying options" not in _render_detail(REQUEST, gadget(variants=[]))
