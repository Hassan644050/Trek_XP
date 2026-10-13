import pytest
from pydantic import ValidationError

from app.models.catalog import GadgetIn, PlacementIn, UserCreate


PLACE = {"name": "Kaptai Lake", "country_code": "bd", "latitude": 22.76, "longitude": 92.276}


def placement(**overrides):
    fields = {"place": PLACE, "trip_types": ["backpacking"], "why": "Boat rides splash phones."}
    fields.update(overrides)
    return PlacementIn(**fields)


def test_placement_defaults_and_normalization():
    p = placement(
        trip_types=["hiking", "backpacking", "hiking"],
        activities=["photography", "photography"],
        why="  Boat   rides\nsplash phones.  ",
    )
    assert [t.value for t in p.trip_types] == ["hiking", "backpacking"]
    assert [a.value for a in p.activities] == ["photography"]
    assert p.priority.value == "recommended"
    assert p.why == "Boat rides splash phones."
    assert p.place.country_code == "BD"


def test_placement_needs_a_trip_type():
    with pytest.raises(ValidationError):
        placement(trip_types=[])


@pytest.mark.parametrize("field,value", [("trip_types", ["space_tourism"]), ("activities", ["skydiving"])])
def test_placement_rejects_values_the_public_form_does_not_offer(field, value):
    with pytest.raises(ValidationError):
        placement(**{field: value})


@pytest.mark.parametrize("lat,lon", [(91, 0), (0, 181)])
def test_placement_rejects_impossible_coordinates(lat, lon):
    with pytest.raises(ValidationError):
        placement(place={**PLACE, "latitude": lat, "longitude": lon})


def test_gadget_text_is_tidied():
    g = GadgetIn(name="  Dry   bag ", category="  ", description="  Keeps things dry.  ")
    assert (g.name, g.category, g.description) == ("Dry bag", None, "Keeps things dry.")


def test_user_email_is_normalized_and_checked():
    assert UserCreate(email=" Rumi@Example.COM ", name="Rumi", password="x" * 10).email == "rumi@example.com"

    with pytest.raises(ValidationError):
        UserCreate(email="not-an-email", name="Rumi", password="x" * 10)


def test_user_role_defaults_to_coordinator():
    assert UserCreate(email="a@b.co", name="A", password="x" * 10).role.value == "coordinator"
