"""load_catalog against a real database: matching, ranking, exclusion set."""

from datetime import date

from app.models.context import TripContext
from app.models.trip import TripRequest
from app.services.gadgets.catalog import load_catalog
from tests.db.conftest import CSRF, run
from tests.db.test_catalog_flow import KAPTAI, add_placement, new_gadget


def ctx(name, lat, lon, trip_type="backpacking", activities=("photography",)):
    trip = TripRequest(
        destination=name, start_date=date(2026, 11, 10), end_date=date(2026, 11, 14),
        trip_type=trip_type, activities=list(activities), latitude=lat, longitude=lon,
    )
    return TripContext(
        trip=trip, resolved_place=name, resolved_latitude=lat, resolved_longitude=lon)


def load(context):
    return run(lambda session: load_catalog(session, context))


def test_catalog_matches_the_destination_and_marks_items_verified(coordinator):
    g = new_gadget(coordinator, "Waterproof Dry Bag", category="Protection")
    add_placement(coordinator, g["id"], place=KAPTAI)

    match = load(ctx("Kaptai Lake", 22.76, 92.276))

    assert [r.gadget for r in match.recommendations] == ["Waterproof Dry Bag"]
    assert match.recommendations[0].verified is True
    assert match.recommendations[0].origin.value == "community"
    assert match.existing_names == ["Waterproof Dry Bag"]


def test_a_far_away_place_with_the_same_name_does_not_match(coordinator):
    g = new_gadget(coordinator, "Dry Bag")
    add_placement(coordinator, g["id"], place=KAPTAI)

    # Same name, but roughly a thousand kilometres away.
    match = load(ctx("Kaptai Lake", 10.0, 80.0))

    assert match.existing_names == []
    assert match.recommendations == []


def test_exclusion_set_covers_every_gadget_not_just_the_shown_ones(coordinator):
    """The model must avoid everything on file for the place, even items
    tagged for a different trip type that are not themselves shown."""
    hiking = new_gadget(coordinator, "Trekking Poles")
    add_placement(coordinator, hiking["id"], place=KAPTAI, trip_types=["hiking"])
    boat = new_gadget(coordinator, "Boat Life Vest")
    add_placement(coordinator, boat["id"], place=KAPTAI, trip_types=["backpacking"])

    match = load(ctx("Kaptai Lake", 22.76, 92.276, trip_type="backpacking"))

    # Shown: only the one tagged for this trip type.
    assert [r.gadget for r in match.recommendations] == ["Boat Life Vest"]
    # Excluded from the model: both, so it cannot re-suggest the hiking item.
    assert set(match.existing_names) == {"Trekking Poles", "Boat Life Vest"}


def test_retired_gadget_is_excluded_from_the_model_but_not_shown(coordinator):
    g = new_gadget(coordinator, "Old Lantern")
    add_placement(coordinator, g["id"], place=KAPTAI)
    coordinator.patch(
        f"/api/coordinator/gadgets/{g['id']}", json={"is_active": False}, headers=CSRF)

    match = load(ctx("Kaptai Lake", 22.76, 92.276))

    assert match.recommendations == []            # retired: not recommended
    assert match.existing_names == ["Old Lantern"]  # but still on file
