"""Sharing a list: the home page's link preview, and counting the channel."""

import re
from types import SimpleNamespace

import pytest

from app.models.recommendation import Priority, Recommendation, RecommendResponse, StopSummary
from app.routes import home
from app.routes.destinations import FormOptions, Option
from app.services import analytics


@pytest.fixture(autouse=True)
def lookups(monkeypatch):
    """Options and the quick list without a database; no cards left over."""
    async def options():
        return FormOptions(trip_types=[Option(value="beach", label="Beach"), Option(value="hiking", label="Hiking")],
                           activities=[Option(value="surfing", label="Surfing")])

    calls = []

    async def quick_list(trip, background, quick):
        calls.append((trip, quick))
        return RecommendResponse(
            destination=trip.destination, duration_days=trip.duration_days,
            recommendations=[Recommendation(gadget="Dry Bag", why="x", priority=Priority.ESSENTIAL),
                             Recommendation(gadget="Sun Hat", why="y")],
            stops=[StopSummary(name="Cox's Bazar", climate_available=True, min_temp_c=17.4, max_temp_c=29.6,
                               plug_types=["A", "C"], voltage="220V", frequency="50Hz")],
        )

    monkeypatch.setattr(home, "form_options", options)
    monkeypatch.setattr(home, "recommend", quick_list)
    home._cards.clear()
    return calls


def meta(page: str, prop: str) -> str | None:
    found = re.search(rf'<meta (?:property|name)="{prop}" content="([^"]*)"', page)
    return found and found.group(1)


def test_slugs_match_the_home_pages_rule():
    assert home.slugify("Cox's Bazar") == "coxs-bazar"
    assert home.slugify("Saint Martin’s Island") == "saint-martins-island"
    assert home.slugify("Rema-Kalenga  Wildlife Sanctuary") == "rema-kalenga-wildlife-sanctuary"


def test_a_shared_trip_gets_its_own_preview(client):
    page = client.get("/?to=coxs-bazar,saint-martins-island&from=2026-11-28&until=2026-12-05"
                      "&types=beach,hiking&ref=share-wa").text

    assert meta(page, "og:title") == "Packing list for Cox&#x27;s Bazar + Saint Martin&#x27;s Island"
    assert meta(page, "og:description").startswith("28 Nov – 5 Dec · Beach, Hiking · Checked against")
    # The card picture, for the trip as understood (no ref tag).
    assert meta(page, "og:image") == ("http://testserver/share/card.png?to=coxs-bazar,saint-martins-island"
                                      "&amp;from=2026-11-28&amp;until=2026-12-05&amp;types=beach,hiking")
    assert "ref=share-wa" in meta(page, "og:url")


def test_unknown_values_never_reach_the_preview(client):
    page = client.get('/?to=nowhere,"><script>&types=beach,free_money&from=2026-13-40').text
    assert meta(page, "og:title") == home.DEFAULT_TITLE        # no known place: the default card
    assert "<script>" not in page.split("<!-- /share-preview -->")[0].split("<!-- share-preview -->")[1]

    page = client.get("/?to=coxs-bazar&types=free_money&from=2026-13-40&until=2026-12-05").text
    assert meta(page, "og:description") == "Checked against the weather, plugs and voltage there."


def test_a_plain_visit_keeps_the_default_card_and_revalidates(client):
    first = client.get("/")
    assert meta(first.text, "og:title") == home.DEFAULT_TITLE
    again = client.get("/", headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304


def test_the_share_channel_is_counted(client):
    client.get("/?to=coxs-bazar&ref=share-wa", headers={"user-agent": "Mozilla/5.0 (Linux; Android 14)"})
    client.get("/?ref=Not%20A%20Tag", headers={"user-agent": "Mozilla/5.0 (Linux; Android 14)"})

    refs = {label for (_, event, label) in analytics._buffer.counts if event == analytics.REFERRER}
    assert refs == {"ref:share-wa"}


# ---------- the card image ----------


def test_the_card_is_drawn_from_the_quick_list_and_cached(client, lookups):
    url = "/share/card.png?to=coxs-bazar&from=2026-11-28&until=2026-12-05&types=beach&acts=surfing&pax=2"
    first = client.get(url)

    assert first.status_code == 200 and first.headers["content-type"] == "image/png"
    assert first.content.startswith(b"\x89PNG")
    trip, quick = lookups[0]
    assert quick is True                                       # never the model
    assert trip.trip_types == ["beach"] and trip.activities == ["surfing"] and trip.travelers == 2

    # Same trip written differently: the same card, not drawn again.
    again = client.get("/share/card.png?pax=2&acts=surfing&types=beach&until=2026-12-05&from=2026-11-28&to=coxs-bazar")
    assert again.content == first.content and len(lookups) == 1


def test_card_text_comes_from_known_values_only():
    trip = home.SharedTrip(places=[SimpleNamespace(name="Cox's Bazar")], types=[("beach", "Beach")])
    assert trip.query() == "to=coxs-bazar&types=beach"


def test_a_link_naming_no_known_place_gets_the_generic_card(client, lookups):
    response = client.get("/share/card.png?to=nowhere")
    assert response.status_code == 200 and response.content.startswith(b"\x89PNG")
    assert lookups == []


def test_the_renderer_copes_with_long_names_and_empty_lists():
    import io

    from PIL import Image

    from app.services.share_card import HEIGHT, WIDTH, Card, CardItem, render

    long = Card(places="Rema-Kalenga Wildlife Sanctuary + Bhimruli Floating Market + Shuvo Sandhya Beach",
                dates="1 Dec – 3 Dec · 3 days", trip="Forest · Birdwatching · Wildlife watching · Camping",
                conditions=["14–28°C", "Plug A/C/D/G/K · 220V"],
                items=[CardItem("A very long gadget name that cannot possibly fit on one line " * 2, "optional")] * 9,
                total=9)
    for card in (long, Card(places="Jaflong")):
        image = Image.open(io.BytesIO(render(card)))
        assert image.size == (WIDTH, HEIGHT)
