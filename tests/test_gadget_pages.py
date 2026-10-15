"""The server-rendered gadget detail page: HTML, SEO tags, escaping."""

import json
import re
from types import SimpleNamespace

from app.routes.gadget_pages import _destinations, _not_found, _render_detail


REQUEST = SimpleNamespace(base_url="https://trekxp.example/")


def placement(place_name, division, trip_types):
    return SimpleNamespace(
        place=SimpleNamespace(name=place_name, division=division),
        trip_types=trip_types,
    )


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


def test_detail_links_each_destination_to_the_personalised_home_page():
    html = _render_detail(REQUEST, gadget())

    # Apostrophe dropped (coxs-bazar), not turned into a dash (cox-s-bazar).
    assert 'href="/?to=cox-s-bazar"' not in html
    assert 'href="/?to=coxs-bazar"' in html
    assert 'href="/?to=saint-martins-island"' in html


def test_destinations_are_unique_and_sorted():
    assert _destinations(gadget()) == [
        ("Cox's Bazar", "Chattogram"),
        ("Saint Martin's Island", "Chattogram"),
    ]


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


def test_detail_offers_same_category_alternatives():
    similar = [other("Rain Poncho", "rain-poncho"), other("Sun Hat", "sun-hat")]
    html = _render_detail(REQUEST, gadget(), similar)

    assert "Other Protection options" in html
    assert 'href="/gadget/rain-poncho"' in html
    assert 'href="/gadget/sun-hat"' in html
    # Destinations remain, now as chips linking to the personalised home page.
    assert 'href="/?to=coxs-bazar"' in html


def test_detail_without_alternatives_omits_the_options_section():
    html = _render_detail(REQUEST, gadget(), [])
    assert "options</h2>" not in html
