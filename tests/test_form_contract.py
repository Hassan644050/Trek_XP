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
