from datetime import date

import pytest
from pydantic import ValidationError

from app.models.trip import TripRequest


def make_trip(**overrides):
    fields = {
        "destination": "Sylhet",
        "start_date": date(2026, 11, 10),
        "end_date": date(2026, 11, 14),
        "trip_type": "hiking",
    }
    fields.update(overrides)
    return TripRequest(**fields)


def test_duration_counts_both_ends():
    assert make_trip().duration_days == 5


def test_same_day_trip_is_one_day():
    day = date(2026, 11, 10)
    assert make_trip(start_date=day, end_date=day).duration_days == 1


def test_end_before_start_is_rejected():
    with pytest.raises(ValidationError, match="end_date must not be before start_date"):
        make_trip(start_date=date(2026, 11, 14), end_date=date(2026, 11, 10))


@pytest.mark.parametrize("travelers", [0, 51])
def test_traveler_count_is_bounded(travelers):
    with pytest.raises(ValidationError):
        make_trip(travelers=travelers)


def test_trip_type_and_activities_are_slugified():
    # Trip types are admin-managed strings now, not an enum; the schema
    # canonicalises them and the form constrains the choices.
    t = make_trip(trip_type="Winter Sports", activities=["Remote Work", "remote_work"])
    assert t.trip_type == "winter_sports"
    assert t.activities == ["remote_work"]  # slugged and de-duplicated


def test_trip_type_must_not_be_blank():
    with pytest.raises(ValidationError):
        make_trip(trip_type="!")


# ---------- several trip types ----------


def test_several_trip_types_are_kept_in_order_and_the_first_is_primary():
    t = make_trip(trip_type=None, trip_types=["Beach", "Hiking", "beach"])
    assert t.trip_types == ["beach", "hiking"]
    assert t.trip_type == "beach"


def test_a_single_trip_type_still_works():
    assert make_trip(trip_type="city").trip_types == ["city"]


def test_a_trip_needs_at_least_one_type_and_at_most_four():
    with pytest.raises(ValidationError, match="at least one trip type"):
        make_trip(trip_type=None)
    with pytest.raises(ValidationError):
        make_trip(trip_type=None, trip_types=["a1", "b2", "c3", "d4", "e5"])
