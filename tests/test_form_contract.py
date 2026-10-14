"""The coordinator page builds its JSON by hand, so it can silently drift
from the schema it posts to.

That is not hypothetical: `district` and `division` were added to PlaceIn
and the API, but the form kept listing fields one by one and dropped them,
so every manually-added place saved with a null district. The API tests
passed throughout, because they post their own payloads and never run the
page's JavaScript.
"""

import re

import pytest

from app.config import PROJECT_ROOT
from app.models.catalog import PlaceIn


COORDINATOR_PAGE = PROJECT_ROOT / "app" / "static" / "coordinator.html"


def _place_literal_keys() -> set[str]:
    """Keys of the `place: { ... }` object the placement form posts."""
    page = COORDINATOR_PAGE.read_text(encoding="utf-8")
    match = re.search(r"place:\s*\{(.*?)\n\s*\},", page, re.DOTALL)

    assert match, "could not find the place payload in the coordinator page"

    return set(re.findall(r"^\s*(\w+):", match.group(1), re.MULTILINE))


def test_form_sends_every_field_the_place_schema_accepts():
    missing = set(PlaceIn.model_fields) - _place_literal_keys()

    assert not missing, (
        f"The placement form does not send {sorted(missing)}. "
        "Add them to the `place:` object in coordinator.html, or they will "
        "be dropped silently when a placement is saved."
    )


def test_form_sends_nothing_the_schema_would_reject():
    extra = _place_literal_keys() - set(PlaceIn.model_fields)
    assert not extra, f"The form sends unknown fields: {sorted(extra)}"


@pytest.mark.parametrize("endpoint", ["/api/coordinator/places/manual", "/api/coordinator/admin-areas"])
def test_page_calls_the_endpoints_it_depends_on(endpoint):
    assert endpoint in COORDINATOR_PAGE.read_text(encoding="utf-8")


# ---------- the home page's default destination ----------

HOME_PAGE = PROJECT_ROOT / "app" / "static" / "index.html"


def test_the_home_page_reads_the_default_destination_flag():
    """The home page opens on one destination, chosen by a flag in the
    dataset. Renaming the field would leave the form empty on load while
    every API test still passed -- the same shape of bug as above."""
    page = HOME_PAGE.read_text(encoding="utf-8")

    assert "is_default" in page, "the home page no longer reads is_default"

    from app.routes.destinations import FeaturedPlace

    assert "is_default" in FeaturedPlace.model_fields


def test_the_home_page_opens_on_a_real_trip_type():
    """The page keeps its own copy of the trip type list, so its default
    can name a value the API would reject."""
    from app.services.taxonomy import SEED_TRIP_TYPES

    page = HOME_PAGE.read_text(encoding="utf-8")
    match = re.search(r'DEFAULT_TRIP_TYPE\s*=\s*"([^"]+)"', page)

    assert match, "could not find DEFAULT_TRIP_TYPE in the home page"

    default = match.group(1)

    assert default in {v for v, _ in SEED_TRIP_TYPES}
    assert default == "beach"


# ---------- the gadget save body ----------


def test_the_gadget_form_posts_exactly_the_create_fields():
    """The gadget editor builds its JSON by hand too. A field added to
    GadgetIn but not to the form saves as null without any error -- the
    same drift that dropped district and division from places."""
    from app.models.catalog import GadgetIn

    page = COORDINATOR_PAGE.read_text(encoding="utf-8")
    # The gadget body is the one object literal that carries is_active.
    match = re.search(r"const body = \{([^}]*is_active[^}]*)\};", page, re.DOTALL)

    assert match, "could not find the gadget save body in the coordinator page"

    posted = set(re.findall(r"(\w+):", match.group(1)))

    assert posted == set(GadgetIn.model_fields)


def test_the_home_page_reads_a_destination_from_the_url():
    """A shared link like /?to=<slug> should land on that destination, so
    the page must parse the URL and personalise. Guards against the wiring
    being removed or renamed."""
    page = HOME_PAGE.read_text(encoding="utf-8")

    # Reads the destination from any of the accepted query params.
    assert 'get("to")' in page
    assert 'get("destination")' in page
    # Detects, matches and personalises.
    for fn in ("startFromUrl", "findDestination", "personalizeHero", "updateUrl"):
        assert fn in page, f"home page no longer defines {fn}"
