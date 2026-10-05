from datetime import date

import pytest

from app.exceptions.exceptions import GadgetSourceException
from app.models.context import ClimateInfo, CountryInfo, TripContext
from app.models.recommendation import Origin, Priority
from app.models.trip import TripRequest
from app.services.gadgets.llm_source import LLMGadgetSource, parse_recommendations
from app.services.gadgets.prompt import build_gadget_prompt
from app.services.llm.base import LLMProvider

ONE_ITEM = '[{"gadget": "Headlamp", "why": "Night trails.", "priority": "essential", "category": "Lighting"}]'


def test_plain_json_array():
    [rec] = parse_recommendations(ONE_ITEM)
    assert (rec.gadget, rec.why, rec.priority, rec.category) == (
        "Headlamp",
        "Night trails.",
        Priority.ESSENTIAL,
        "Lighting",
    )


def test_markdown_fences_are_stripped():
    assert len(parse_recommendations(f"```json\n{ONE_ITEM}\n```")) == 1


def test_preamble_around_the_array_is_ignored():
    assert len(parse_recommendations(f"Here is your list:\n{ONE_ITEM}\nEnjoy!")) == 1


def test_malformed_entries_are_skipped_not_fatal():
    raw = '[{"gadget": "Headlamp", "why": "Night trails."}, {"gadget": "No reason"}, "junk", {"why": "No name"}]'
    assert [r.gadget for r in parse_recommendations(raw)] == ["Headlamp"]


@pytest.mark.parametrize(
    ("raw_priority", "expected"),
    [("ESSENTIAL", Priority.ESSENTIAL), (" optional ", Priority.OPTIONAL), ("critical", Priority.RECOMMENDED)],
)
def test_priority_is_normalized(raw_priority, expected):
    raw = f'[{{"gadget": "Adapter", "why": "Plugs.", "priority": "{raw_priority}"}}]'
    assert parse_recommendations(raw)[0].priority == expected


def test_model_cannot_mark_its_own_output_verified():
    raw = '[{"gadget": "Adapter", "why": "Plugs.", "origin": "community", "verified": true}]'
    [rec] = parse_recommendations(raw)
    assert rec.origin == Origin.LLM
    assert rec.verified is False


@pytest.mark.parametrize("raw", ["not json at all", '{"gadget": "Adapter"}'])
def test_unreadable_reply_is_an_error(raw):
    with pytest.raises(GadgetSourceException):
        parse_recommendations(raw)


def make_context(**overrides):
    fields = {
        "trip": TripRequest(
            destination="sylhet!!",
            start_date=date(2026, 11, 10),
            end_date=date(2026, 11, 14),
            trip_type="hiking",
            activities=["camping"],
            baggage="carry_on_only",
        ),
        "resolved_place": "Sylhet",
        "climate": ClimateInfo(summary="Typical conditions: hot and mostly dry."),
        "country": CountryInfo(
            country_name="Bangladesh", plug_types=["A", "C", "G"], voltage="220V", frequency="50Hz"
        ),
    }
    fields.update(overrides)
    return TripContext(**fields)


def test_prompt_is_grounded_in_trip_facts():
    prompt = build_gadget_prompt(make_context())
    assert "Destination: Sylhet, Bangladesh" in prompt
    assert "Plug type A/C/G, 220V 50Hz." in prompt
    assert "hot and mostly dry" in prompt
    assert "carry-on only" in prompt
    assert "(5 days)" in prompt
    # The geocoder's name is used, never the raw user string.
    assert "sylhet!!" not in prompt


def test_prompt_admits_missing_data():
    prompt = build_gadget_prompt(
        make_context(climate=ClimateInfo(available=False), country=CountryInfo(available=False))
    )
    assert "No weather information is available" in prompt
    assert "Plug and voltage information is not available" in prompt


class RecordingProvider(LLMProvider):
    def __init__(self, reply):
        self.reply = reply
        self.prompts = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        return self.reply


def test_source_sends_prompt_and_parses_reply():
    provider = RecordingProvider(ONE_ITEM)
    recs = LLMGadgetSource(provider=provider).recommend(make_context())

    assert [r.gadget for r in recs] == ["Headlamp"]
    assert len(provider.prompts) == 1
    assert "Plug type A/C/G" in provider.prompts[0]
