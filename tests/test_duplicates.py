"""Merging one gadget into another (duplicates.merge_into)."""

from types import SimpleNamespace

import pytest

from app.exceptions.exceptions import InvalidInputException
from app.services.gadgets.duplicates import merge_into


def gadget(id, name, *, places=(), variants=(), active=True, status=None, count=0, image=None, **fields):
    base = dict(description=None, category=None, brand=None, model_name=None, color=None)
    base.update(fields)
    return SimpleNamespace(
        id=id, name=name, is_active=active, review_status=status, suggestion_count=count, image_key=image,
        placements=[SimpleNamespace(place_id=p, why=f"{name} at {p}") for p in places],
        variants=[SimpleNamespace(brand=v) for v in variants], **base,
    )


def test_merge_moves_new_places_and_all_variants_and_fills_gaps():
    kept = gadget(1, "Dry Bag", places=[10], variants=["Sea to Summit"], category="Protection")
    gone = gadget(2, "Waterproof dry Bag", places=[10, 11], variants=["Generic"],
                  description="Roll-top bag.", category="Gear", count=3)

    leftover = merge_into(gone, kept)

    assert [p.place_id for p in kept.placements] == [10, 11]       # place 10 kept its own reason
    assert kept.placements[0].why == "Dry Bag at 10"
    assert [v.brand for v in kept.variants] == ["Sea to Summit", "Generic"]
    assert kept.description == "Roll-top bag." and kept.category == "Protection"  # gap filled, own value kept
    assert kept.suggestion_count == 3
    assert leftover is None


def test_merging_a_live_gadget_into_a_pending_one_publishes_it():
    kept = gadget(1, "Bluetooth Speaker", active=False, status="pending")
    merge_into(gadget(2, "Portable Bluetooth Speaker", active=True), kept)
    assert kept.is_active and kept.review_status == "approved"


def test_the_image_moves_if_the_kept_gadget_has_none_otherwise_it_is_returned_for_deletion():
    kept = gadget(1, "A")
    assert merge_into(gadget(2, "B", image="gadgets/b.webp"), kept) is None
    assert kept.image_key == "gadgets/b.webp"

    kept = gadget(1, "A", image="gadgets/a.webp")
    assert merge_into(gadget(2, "B", image="gadgets/b.webp"), kept) == "gadgets/b.webp"
    assert kept.image_key == "gadgets/a.webp"


def test_a_gadget_cannot_be_merged_into_itself():
    g = gadget(1, "A")
    with pytest.raises(InvalidInputException):
        merge_into(g, g)
