"""Multi-stop trips and the traveller's gender: request model, prompt,
which-stop tagging, catalog merging and the route's response."""

import datetime as dt
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.models.context import ClimateInfo, CountryInfo, StopContext, TripContext
from app.models.recommendation import Priority, Recommendation
from app.models.trip import TripRequest
from app.routes import recommend
from app.services.gadgets.catalog import CatalogMatch
from app.services.gadgets.llm_source import parse_recommendations
from app.services.gadgets.prompt import build_gadget_prompt

BD = CountryInfo(available=True, country_name="Bangladesh", country_code="BD",
                 plug_types=["A", "C", "D", "G", "K"], voltage="220V", frequency="50Hz")
DATES = dict(start_date=dt.date(2026, 11, 24), end_date=dt.date(2026, 12, 1))


def stop(name, summary="warm and mostly dry; 18°C to 30°C."):
    return StopContext(name=name, latitude=21.4, longitude=92.0,
                       climate=ClimateInfo(available=bool(summary), summary=summary), country=BD)


def route_context(*names, gender=None):
    trip = TripRequest(trip_type="beach", travelers=2, gender=gender,
                       stops=[{"name": n} for n in names], **DATES)
    stops = [stop(n) for n in names]
    return TripContext(trip=trip, resolved_place=" + ".join(names), climate=stops[0].climate,
                       country=BD, stops=stops, novel_item_count=5)


# ---------- request model ----------

def test_stops_name_the_trip_and_are_capped():
    trip = TripRequest(trip_type="beach", stops=[{"name": "Cox's Bazar"}, {"name": "Saint Martin's Island"}], **DATES)
    assert trip.destination == "Cox's Bazar + Saint Martin's Island"

    with pytest.raises(ValidationError):
        TripRequest(trip_type="beach", stops=[{"name": f"Place {i}"} for i in range(6)], **DATES)
    with pytest.raises(ValidationError):
        TripRequest(trip_type="beach", **DATES)                       # neither destination nor stops


def test_gender_is_optional_and_checked():
    assert TripRequest(destination="Jaflong", trip_type="hiking", **DATES).gender is None
    assert TripRequest(destination="Jaflong", trip_type="hiking", gender="mixed", **DATES).gender == "mixed"
    with pytest.raises(ValidationError):
        TripRequest(destination="Jaflong", trip_type="hiking", gender="other", **DATES)


# ---------- prompt ----------

def test_a_route_prompt_lists_every_stop_and_asks_which_stop():
    prompt = build_gadget_prompt(route_context("Cox's Bazar", "Saint Martin's Island"))

    assert "1. Cox's Bazar, Bangladesh" in prompt and "2. Saint Martin's Island, Bangladesh" in prompt
    assert "Saint Martin's Island: warm and mostly dry" in prompt
    assert prompt.count("Bangladesh: plug type A/C/D/G/K") == 1         # plugs once per country
    assert '"for"' in prompt


def test_gender_reaches_the_prompt_only_when_given():
    assert "Travellers: 2 (women)" in build_gadget_prompt(route_context("A place", "B place", gender="female"))
    assert "do not stereotype" in build_gadget_prompt(route_context("A place", "B place", gender="male"))
    plain = build_gadget_prompt(route_context("A place", "B place"))
    assert "Travellers: 2\n" in plain and "stereotype" not in plain


def test_the_model_says_which_stops_an_item_is_for():
    (rec,) = parse_recommendations('[{"gadget": "Snorkel Set", "why": "Coral reefs.", "for": ["Saint Martin\'s Island"]}]')
    assert rec.stops == ["Saint Martin's Island"]


def test_stop_names_are_checked_against_the_trip():
    ctx = route_context("Cox's Bazar", "Saint Martin's Island")
    fit = lambda stops: recommend._fit_stops(Recommendation(gadget="x", why="y", stops=stops), ctx).stops

    assert fit(["saint martin's island"]) == ["Saint Martin's Island"]    # spelled as the trip spells it
    assert fit(["Atlantis"]) == []                                         # not a stop: whole trip
    assert fit(["Cox's Bazar", "Saint Martin's Island"]) == []             # every stop: whole trip


def test_longer_routes_ask_for_more_new_items():
    assert recommend._novel_count(route_context("A place")) == 5
    assert recommend._novel_count(route_context("A place", "B place", "C place")) == 9


# ---------- catalog across stops ----------

def test_catalog_items_are_merged_across_stops():
    def match(*names):
        return CatalogMatch(
            recommendations=[Recommendation(gadget=n, why="w", priority=Priority.ESSENTIAL, verified=True) for n in names],
            existing_names=list(names),
        )

    merged = recommend._merge_route_catalog([
        ("Cox's Bazar", match("Reef-Safe Sunscreen", "Dry Bag")),
        ("Saint Martin's Island", match("Waterproof dry Bag", "Snorkel Set")),   # same item as Dry Bag
    ])

    assert {r.gadget: r.stops for r in merged.recommendations} == {
        "Reef-Safe Sunscreen": ["Cox's Bazar"],
        "Dry Bag": [],                                   # at both stops: the whole trip
        "Snorkel Set": ["Saint Martin's Island"],
    }
    assert merged.existing_names == ["Reef-Safe Sunscreen", "Dry Bag", "Snorkel Set"]
