"""Unit tests for the taxonomy helpers that need no database."""

import pytest

from app.services.taxonomy import slugify


@pytest.mark.parametrize(
    "label,expected",
    [
        ("Beach", "beach"),
        ("Winter Sports", "winter_sports"),
        ("  Remote  Work  ", "remote_work"),
        ("Bird-Watching!", "bird_watching"),
        ("Café Tour", "caf_tour"),
        ("日本", ""),
    ],
)
def test_slugify(label, expected):
    assert slugify(label) == expected


def test_slugify_is_capped_at_thirty_characters():
    assert len(slugify("x" * 50)) == 30
