"""Saving the model's new suggestions for review: name matching, the
description parser, the catalog exclusion rule and scheduling."""

from types import SimpleNamespace

import pytest

from app.models.recommendation import Priority, Recommendation
from app.services.gadgets.catalog import _existing_names
from app.services.gadgets.suggestions import _parse_description, find_match, same_gadget


@pytest.mark.parametrize("a,b,same", [
    ("Portable Bluetooth Speaker", "Bluetooth Speaker", True),
    ("bluetooth  speaker", "Bluetooth Speaker", True),
    ("Universal Travel Adapter (Type D/G)", "universal travel adapter", True),
    ("Power Bank", "Power Bank 20,000mAh", True),      # specs are ignored
    ("Portable Charger", "Power Bank", True),           # synonyms
    ("Dry Bag", "Dry Shampoo", False),
    ("Dry Bag", "Sleeping Bag", False),
    ("Sun Hat", "Hat", False),                          # only "possibly" the same: a coordinator decides
    ("", "Hat", False),
])
def test_same_gadget(a, b, same):
    assert same_gadget(a, b) is same


def test_find_match_returns_the_closest_existing_gadget():
    gadgets = [SimpleNamespace(name="Speaker Stand Bluetooth Speaker"), SimpleNamespace(name="Bluetooth Speaker"),
               SimpleNamespace(name="Dry Bag")]
    assert find_match("Portable Bluetooth Speaker", gadgets).name == "Bluetooth Speaker"
    assert find_match("Wireless Speaker", gadgets).name == "Bluetooth Speaker"
    assert find_match("E-Reader", gadgets) is None


@pytest.mark.parametrize("raw,expected", [
    ('{"description": "A small speaker.  Look for IPX7.", "category": "Audio"}',
     ("A small speaker. Look for IPX7.", "Audio")),
    ('```json\n{"description": "Text", "category": ""}\n```', ("Text", None)),
    ("Sure! Here it is: {\"description\": \"Text\"} hope that helps", ("Text", None)),
    ("not json at all", (None, None)),
    ('["a list"]', (None, None)),
])
def test_parse_description(raw, expected):
    assert _parse_description(raw) == expected


def placement(name, status=None):
    return SimpleNamespace(gadget=SimpleNamespace(name=name, review_status=status))


def test_pending_suggestions_are_not_excluded_from_the_model():
    names = _existing_names([
        placement("Dry Bag"),
        placement("Portable Bluetooth Speaker", "pending"),
        placement("Snow Chains", "rejected"),
    ])
    # Pending: the model may suggest it again (adding to its count).
    # Rejected: stays listed, so the model is steered away from it.
    assert names == ["Dry Bag", "Snow Chains"]


def test_recommend_schedules_suggestions_with_a_copy_of_the_trip(monkeypatch):
    from app.routes import recommend

    added = []
    background = SimpleNamespace(add_task=lambda fn, *args: added.append((fn, args)))
    monkeypatch.setattr(recommend, "get_sessionmaker", lambda: "SESSIONMAKER")
    context = SimpleNamespace(
        resolved_place="Cox's Bazar",
        trip=SimpleNamespace(destination="Cox's Bazar", country_code="bd", trip_type="beach"),
        country=SimpleNamespace(country_code="BD"),
    )
    novel = [Recommendation(gadget="Portable Bluetooth Speaker", why="Music on the beach.", priority=Priority.OPTIONAL)]

    recommend._schedule_suggestions(background, context, novel)

    (fn, (sessionmaker, batch)), = added
    assert fn is recommend.record_and_enrich and sessionmaker == "SESSIONMAKER"
    assert (batch.place_name, batch.country_code, batch.trip_type) == ("Cox's Bazar", "BD", "beach")
    assert [r.gadget for r in batch.suggestions] == ["Portable Bluetooth Speaker"]


def test_nothing_is_scheduled_without_new_items(monkeypatch):
    from app.routes import recommend

    added = []
    recommend._schedule_suggestions(SimpleNamespace(add_task=lambda *a: added.append(a)), None, [])
    assert added == []


def test_a_travellers_list_drops_reworded_duplicates_of_catalog_items():
    from app.services.gadgets.llm_source import _novel

    context = SimpleNamespace(existing_gadgets=["Portable Bluetooth Speaker", "Power Bank"], novel_item_count=5)
    model_items = [
        Recommendation(gadget="Bluetooth Speaker", why="x"),          # = catalog speaker
        Recommendation(gadget="Portable Charger", why="x"),           # = catalog power bank
        Recommendation(gadget="Headlamp", why="x"),
        Recommendation(gadget="LED Head Torch", why="x"),             # = the headlamp just above
        Recommendation(gadget="Dry Bag", why="x"),
    ]

    assert [r.gadget for r in _novel(model_items, context)] == ["Headlamp", "Dry Bag"]
