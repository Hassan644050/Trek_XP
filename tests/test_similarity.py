"""Gadget name similarity: the same item under different names scores
SAME, look-alikes score POSSIBLE, different items score low."""

import pytest

from app.services.gadgets.similarity import POSSIBLE, SAME, canonical, similarity

SAME_ITEM = [
    ("Portable Bluetooth Speaker", "Bluetooth Speaker"),
    ("Wireless Speaker", "Bluetooth Speaker"),
    ("Sunglass", "Sunglasses"),
    ("Sunglases", "Sunglasses"),                                  # typo
    ("Power Bank", "Portable Power Bank (20,000mAh)"),
    ("Power Bank", "Power Bank 20000mAh"),
    ("Portable Charger", "Power Bank"),
    ("Travel Plug Adapter", "Universal Travel Adapter"),
    ("Type D/G Travel Plug Adapter", "Universal Travel Adapter (Type D/G)"),
    ("Headlamp", "LED Head Torch"),
    ("Flashlight", "Torch"),
    ("Quick-Dry Towel", "Quick Dry Travel Towel"),
    ("Dry Bag", "Waterproof dry Bag"),
    ("First-Aid Kit", "First Aid Kit"),
    ("Insect Repellent", "Mosquito Repellent Spray"),
    ("Water-Resistant Phone Pouch", "Waterproof Phone Pouch"),
    ("Sunscreen Spray", "Sunscreen"),
]

DIFFERENT_ITEMS = [
    ("Dry Bag", "Dry Shampoo"),
    ("Dry Bag", "Sleeping Bag"),
    ("Water Shoes", "Trekking Shoes"),
    ("Power Bank", "Power Strip"),
    ("Headlamp", "Torch"),
    ("Snorkel Set", "Snorkel Mask"),
    ("Water Purifier Bottle", "Reusable Water Bottle"),
    ("Reef-Safe Sunscreen", "Sunscreen (SPF 50)"),
    ("Universal Travel Adapter", "Multi-Port USB Wall Charger"),
]

LOOK_ALIKES = [("Sun Hat", "Hat"), ("E-Reader", "Kindle E-Reader")]


@pytest.mark.parametrize("a,b", SAME_ITEM)
def test_the_same_item_scores_same(a, b):
    assert similarity(a, b) >= SAME
    assert similarity(b, a) == similarity(a, b)


@pytest.mark.parametrize("a,b", DIFFERENT_ITEMS)
def test_different_items_score_low(a, b):
    assert similarity(a, b) < POSSIBLE


@pytest.mark.parametrize("a,b", LOOK_ALIKES)
def test_look_alikes_are_left_to_a_coordinator(a, b):
    assert POSSIBLE <= similarity(a, b) < SAME


def test_canonical_drops_specs_and_maps_synonyms():
    assert canonical("Type D/G Travel Plug Adapter") == ("travel", "adapter")
    assert canonical("Power Bank (20,000mAh) 65W") == ("power", "bank")
    assert canonical("Portable Charger") == ("power", "bank")
    assert canonical("Sunglasses") == ("sunglass",)


def test_empty_names_never_match():
    assert similarity("", "Hat") == 0.0
    assert similarity("(spf 50)", "Sunscreen") == 0.0
