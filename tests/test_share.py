"""Sharing a list: the home page's link preview, and counting the channel."""

import re
from types import SimpleNamespace

import pytest

from app.routes import home
from app.routes.destinations import FormOptions, Option
from app.services import analytics


@pytest.fixture(autouse=True)
def lookups(monkeypatch):
    """Options and hero photos without a database."""
    async def options():
        return FormOptions(trip_types=[Option(value="beach", label="Beach"), Option(value="hiking", label="Hiking")],
                           activities=[])

    async def heroes(country=None):
        return [SimpleNamespace(place_slug="coxs-bazar", small_url="/media/heroes/cox.webp", alt="The beach at dusk")]

    monkeypatch.setattr(home, "form_options", options)
    monkeypatch.setattr(home, "hero_images", heroes)


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
    assert meta(page, "og:image") == "http://testserver/media/heroes/cox.webp"
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
