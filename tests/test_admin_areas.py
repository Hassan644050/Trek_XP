import math

import pytest

from app.services.destination.admin_areas import (
    district_names,
    districts,
    divisions,
    find_district,
    normalize,
)


BD = "BD"
BANGLADESH_BOUNDS = (20.5, 26.7, 88.0, 92.8)  # south, north, west, east


def test_all_eight_divisions_are_present():
    assert divisions(BD) == [
        "Barishal", "Chattogram", "Dhaka", "Khulna",
        "Mymensingh", "Rajshahi", "Rangpur", "Sylhet",
    ]


def test_all_sixty_four_districts_are_present():
    assert len(district_names(BD)) == 64


@pytest.mark.parametrize(
    ("division", "expected"),
    [
        ("Sylhet", ["Habiganj", "Moulvibazar", "Sunamganj", "Sylhet"]),
        ("Mymensingh", ["Jamalpur", "Mymensingh", "Netrokona", "Sherpur"]),
    ],
)
def test_districts_are_listed_per_division(division, expected):
    assert district_names(BD, division) == expected


def test_every_district_sits_inside_bangladesh():
    south, north, west, east = BANGLADESH_BOUNDS

    for district in set(districts(BD).values()):
        assert south <= district.latitude <= north, district
        assert west <= district.longitude <= east, district


def test_districts_cluster_inside_their_own_division():
    """Guards against the failure that made this dataset necessary: a
    gazetteer returning a same-named place in the wrong part of the country."""
    by_division: dict[str, list] = {}

    for district in set(districts(BD).values()):
        by_division.setdefault(district.division, []).append(district)

    for division, members in by_division.items():
        lats = sorted(d.latitude for d in members)
        lons = sorted(d.longitude for d in members)
        mid_lat, mid_lon = lats[len(lats) // 2], lons[len(lons) // 2]

        for d in members:
            km = math.hypot(
                (d.latitude - mid_lat) * 111,
                (d.longitude - mid_lon) * 111 * math.cos(math.radians(d.latitude)),
            )
            # Chattogram runs ~300km north to south, so this is generous.
            assert km < 200, f"{d.name} is {km:.0f}km from the middle of {division}"


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("Sylhet", "Sylhet"),
        ("sylhet", "Sylhet"),
        ("  SYLHET  ", "Sylhet"),
        ("Chittagong", "Chattogram"),   # renamed in 2018
        ("Comilla", "Cumilla"),
        ("Jessore", "Jashore"),
        ("Bogra", "Bogura"),
        ("Cox's Bazar", "Cox's Bazar"),
        ("coxs bazar", "Cox's Bazar"),
        ("Netrakona", "Netrokona"),
    ],
)
def test_old_and_informal_spellings_still_match(typed, expected):
    assert find_district(BD, typed).name == expected


@pytest.mark.parametrize("typed", [None, "", "Atlantis", "Rajshahi Division"])
def test_unknown_names_return_nothing(typed):
    assert find_district(BD, typed) is None


def test_sylhet_district_covers_the_sada_pathor_area():
    # Sada Pathor is unmapped, so its placement anchors to Sylhet district.
    # Close enough that the climate lookup is for the same weather.
    sylhet = find_district(BD, "Sylhet")
    km = math.hypot(
        (25.19 - sylhet.latitude) * 111,
        (91.72 - sylhet.longitude) * 111 * math.cos(math.radians(25.19)),
    )
    assert km < 60


def test_normalize_ignores_case_accents_and_punctuation():
    assert normalize("Cox's Bazar") == normalize("coxs  bazar") == "coxsbazar"
    assert normalize("Kuakāta") == normalize("Kuakata")
