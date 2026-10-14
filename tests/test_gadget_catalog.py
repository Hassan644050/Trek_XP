"""Catalog logic that needs no database: ranking, exclusion, the prompt.

Matching against a real database lives in tests/db/test_catalog_lookup.py.
"""

from datetime import date
from types import SimpleNamespace

from app.models.context import TripContext
from app.models.recommendation import Origin, Priority, Recommendation
from app.models.trip import TripRequest
from app.services.gadgets.catalog import _existing_names, _relevant
from app.services.gadgets.llm_source import _novel
from app.services.gadgets.prompt import build_gadget_prompt


def trip(trip_type="beach", activities=()):
    return TripRequest(
        destination="Cox's Bazar", start_date=date(2026, 11, 10),
        end_date=date(2026, 11, 14), trip_type=trip_type, activities=list(activities),
        latitude=21.45, longitude=91.96,
    )


def context(existing=(), count=None, **trip_kwargs):
    return TripContext(
        trip=trip(**trip_kwargs), resolved_place="Cox's Bazar",
        existing_gadgets=list(existing), novel_item_count=count,
    )


def placement(name, *, trip_types, activities=(), priority=Priority.RECOMMENDED, active=True):
    return SimpleNamespace(
        trip_types=list(trip_types), activities=list(activities), priority=priority,
        why=f"Why {name}.",
        gadget=SimpleNamespace(name=name, category="Cat", is_active=active),
    )


# ---------- excluding what the catalog already has ----------


def test_novel_drops_names_already_in_the_catalog():
    recs = [Recommendation(gadget=n, why="x") for n in ["Power Bank", "Snorkel Mask"]]
    kept = _novel(recs, context(existing=["power  bank"]))  # loose match

    assert [r.gadget for r in kept] == ["Snorkel Mask"]


def test_novel_drops_repeats_within_one_reply():
    recs = [Recommendation(gadget=n, why="x") for n in ["Dry Bag", "dry bag", "Torch"]]

    assert [r.gadget for r in _novel(recs, context())] == ["Dry Bag", "Torch"]


def test_novel_caps_to_the_requested_count():
    recs = [Recommendation(gadget=f"Item {i}", why="x") for i in range(9)]

    assert len(_novel(recs, context(count=5))) == 5


def test_novel_keeps_everything_when_no_count_is_set():
    recs = [Recommendation(gadget=f"Item {i}", why="x") for i in range(9)]

    assert len(_novel(recs, context(count=None))) == 9


# ---------- the exclusion list in the prompt ----------


def test_prompt_lists_every_existing_item_and_asks_for_exactly_the_count():
    names = [f"Gadget {i}" for i in range(50)]
    prompt = build_gadget_prompt(context(existing=names, count=5))

    assert "Recommend exactly 5 items." in prompt
    assert "ALREADY RECOMMENDED" in prompt
    # All 50 are named, however long the list is.
    assert all(name in prompt for name in names)


def test_prompt_omits_the_exclusion_block_when_there_is_nothing_to_exclude():
    assert "ALREADY RECOMMENDED" not in build_gadget_prompt(context())


# ---------- ranking the catalog items ----------


def test_existing_names_are_distinct_and_include_retired_gadgets():
    placements = [
        placement("Dry Bag", trip_types=["beach"]),
        placement("Dry Bag", trip_types=["hiking"]),   # same gadget, another placement
        placement("Old Torch", trip_types=["beach"], active=False),
    ]

    assert _existing_names(placements) == ["Dry Bag", "Old Torch"]


def test_relevant_prefers_the_trip_type_then_activity_overlap_then_priority():
    placements = [
        placement("Beach Umbrella", trip_types=["beach"], priority=Priority.OPTIONAL),
        placement("Reef Sunscreen", trip_types=["beach"], activities=["diving"],
                  priority=Priority.RECOMMENDED),
        placement("Mountain Boots", trip_types=["hiking"], priority=Priority.ESSENTIAL),
    ]
    recs = _relevant(placements, context(trip_type="beach", activities=["diving"]))

    names = [r.gadget for r in recs]
    # Hiking-only item is excluded; diving-matched item leads on overlap.
    assert "Mountain Boots" not in names
    assert names[0] == "Reef Sunscreen"
    assert set(names) == {"Reef Sunscreen", "Beach Umbrella"}
    assert all(r.origin == Origin.COMMUNITY and r.verified for r in recs)


def test_relevant_falls_back_to_all_active_when_nothing_matches_the_trip_type():
    placements = [placement("Headlamp", trip_types=["hiking"], priority=Priority.ESSENTIAL)]

    recs = _relevant(placements, context(trip_type="beach"))

    assert [r.gadget for r in recs] == ["Headlamp"]


def test_relevant_skips_retired_gadgets():
    placements = [placement("Old Compass", trip_types=["beach"], active=False)]

    assert _relevant(placements, context(trip_type="beach")) == []
