"""Merging catalog places (with or without gadgets) into the home-page picker."""

from types import SimpleNamespace

from app.routes.destinations import FeaturedDivision, FeaturedPlace, _merge


def curated_bd():
    return [
        FeaturedDivision(name="Dhaka", places=[
            FeaturedPlace(name="Dhaka", latitude=23.71, longitude=90.41, is_default=True),
            FeaturedPlace(name="Sonargaon", latitude=23.65, longitude=90.61),
        ]),
        FeaturedDivision(name="Chattogram", places=[
            FeaturedPlace(name="Cox's Bazar", latitude=21.45, longitude=91.96),
        ]),
    ]


def place(name, lat, lon, division=None, country_code="BD"):
    return SimpleNamespace(
        name=name, latitude=lat, longitude=lon, division=division,
        country_code=country_code, country_name="Bangladesh")


def test_a_catalog_place_is_added_to_its_division():
    # Nikli: a coordinator-entered place in Dhaka division.
    merged = _merge(curated_bd(), [place("Nikli", 24.31, 90.95, division="Dhaka")], "BD")

    dhaka = next(d for d in merged if d.name == "Dhaka")
    assert [p.name for p in dhaka.places] == ["Dhaka", "Sonargaon", "Nikli"]


def test_division_is_inferred_when_the_place_has_none():
    # A geocoded place stores no division; it is filed by its coordinates.
    merged = _merge(curated_bd(), [place("Nikli", 24.31, 90.95)], "BD")

    dhaka = next(d for d in merged if d.name == "Dhaka")
    assert "Nikli" in [p.name for p in dhaka.places]


def test_a_place_already_curated_is_not_duplicated():
    merged = _merge(curated_bd(), [place("Cox's Bazar", 21.45, 91.96, division="Chattogram")], "BD")

    chattogram = next(d for d in merged if d.name == "Chattogram")
    assert [p.name for p in chattogram.places].count("Cox's Bazar") == 1


def test_a_place_with_no_locatable_division_is_skipped():
    # Coordinates outside Bangladesh cannot be filed under any BD heading.
    merged = _merge(curated_bd(), [place("Bangkok", 13.75, 100.5)], "BD")

    assert "Bangkok" not in [p.name for d in merged for p in d.places]


def test_a_catalog_only_division_becomes_a_new_group():
    merged = _merge(curated_bd(), [place("Rangpur Spot", 25.74, 89.27, division="Rangpur")], "BD")

    assert "Rangpur" in [d.name for d in merged]
    rangpur = next(d for d in merged if d.name == "Rangpur")
    assert [p.name for p in rangpur.places] == ["Rangpur Spot"]
