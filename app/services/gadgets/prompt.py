from app.models.context import TripContext


MIN_ITEMS = 5
MAX_ITEMS = 8

# Cards are image-led, so the reason is read as a caption rather than a
# paragraph. Shorter also means fewer output tokens, which dominate cost.
MAX_WHY_WORDS = 18
MAX_DESCRIPTION_WORDS = 25


def _place_label(context: TripContext) -> str:
    place = context.resolved_place
    country = context.country.country_name

    if place and country and place != country:
        return f"{place}, {country}"

    return place or country or "the destination"


def _power_line(context: TripContext) -> str:
    country = context.country

    if not country.available or not country.plug_types:
        return "Plug and voltage information is not available for this country."

    plugs = "/".join(country.plug_types)

    return (
        f"Plug type {plugs}, {country.voltage} {country.frequency}."
    )


def _multi(context: TripContext) -> bool:
    return len(context.stops) > 1


def _stops_block(context: TripContext) -> str:
    """Destination and conditions lines: one place, or each stop of a route."""
    if not _multi(context):
        conditions = (
            context.climate.summary
            if context.climate.available and context.climate.summary
            else "No weather information is available for these dates."
        )
        return f"Destination: {_place_label(context)}", conditions

    lines, conditions = [], []
    for i, stop in enumerate(context.stops, 1):
        country = stop.country.country_name
        lines.append(f"{i}. {stop.name}" + (f", {country}" if country and country != stop.name else ""))
        weather = (stop.climate.summary if stop.climate.available and stop.climate.summary
                   else "No weather information is available for these dates.")
        conditions.append(f"{stop.name}: {weather}")
    return "Destinations, visited in this order:\n" + "\n".join(lines), "\n".join(conditions)


def _power_block(context: TripContext) -> str:
    if not _multi(context):
        return _power_line(context)

    # One line per country: plugs are national, not per stop.
    seen, lines = set(), []
    for stop in context.stops:
        key = stop.country.country_code or stop.country.country_name or stop.name
        if key in seen:
            continue
        seen.add(key)
        c = stop.country
        if not c.available or not c.plug_types:
            lines.append(f"{c.country_name or stop.name}: plug and voltage information is not available.")
        else:
            lines.append(f"{c.country_name}: plug type {'/'.join(c.plug_types)}, {c.voltage} {c.frequency}.")
    return "\n".join(lines)


_GENDER_WORDS = {"female": "women", "male": "men", "mixed": "a mixed group"}


def _travellers_line(context: TripContext) -> str:
    trip = context.trip
    who = _GENDER_WORDS.get(trip.gender or "")
    return f"Travellers: {trip.travelers}" + (f" ({who})" if who else "")


def _gender_instruction(context: TripContext) -> str:
    who = _GENDER_WORDS.get(context.trip.gender or "")
    if not who:
        return ""
    return (f"\n- The travellers are {who}. Include gender-specific items only where they genuinely\n"
            "  matter for this trip; do not stereotype.")


def _stops_instruction(context: TripContext) -> str:
    if not _multi(context):
        return ""
    return ("\n- This trip has several destinations. Cover the whole route, and for an item needed\n"
            "  at only some stops, list those stop names in \"for\" (exactly as written above).\n"
            "  Leave \"for\" empty for items needed throughout.")


def _count_instruction(context: TripContext) -> str:
    if context.novel_item_count is not None:
        return f"- Recommend exactly {context.novel_item_count} items."

    return f"- Recommend between {MIN_ITEMS} and {MAX_ITEMS} items."


def _exclusions_block(context: TripContext) -> str:
    """List what the catalog already covers, so the model does not repeat it.

    These are the gadgets coordinators have already entered for this place.
    The whole point of asking the model is to add items beyond them, so they
    are named explicitly however long the list is.
    """
    if not context.existing_gadgets:
        return ""

    listed = "\n".join(f"- {name}" for name in context.existing_gadgets)

    return (
        "\nALREADY RECOMMENDED FOR THIS DESTINATION (do not repeat these or "
        "close variants of them; suggest genuinely different items):\n"
        f"{listed}\n"
    )


def build_gadget_prompt(context: TripContext) -> str:
    """Turn a trip context into a grounded request for gadget suggestions.

    Only the four descriptive fields are asked for. Provenance (origin,
    verified) and warnings are set by our own code -- the model does not get
    to declare its suggestions verified or safe.
    """
    trip = context.trip

    activities = (
        ", ".join(trip.activities)
        if trip.activities
        else "none specified"
    )

    destination_lines, conditions = _stops_block(context)

    # Omitted entirely when unknown: stating a baggage rule the traveller
    # never gave would be inventing a trip fact, and the prompt forbids that.
    if trip.baggage is None:
        baggage_line = ""
    else:
        note = (
            "carry-on only -- spare lithium batteries and power banks must travel "
            "in the cabin, never in checked luggage"
            if trip.baggage.value == "carry_on_only"
            else "checked luggage allowed"
        )
        baggage_line = f"Baggage: {note}\n"

    return f"""You are a travel gear advisor. Recommend the gadgets and electronics a traveller should take on this specific trip.

TRIP
{destination_lines}
Dates: {trip.start_date} to {trip.end_date} ({trip.duration_days} days)
Trip type: {", ".join(trip.trip_types)}
Activities: {activities}
{baggage_line}{_travellers_line(context)}

CONDITIONS
{conditions}

POWER
{_power_block(context)}
{_exclusions_block(context)}
INSTRUCTIONS
{_count_instruction(context)}
- Base every recommendation on the trip facts above. Do not invent weather,
  voltage or plug details that are not stated.
- If a plug type is given, include the correct travel adapter and name the type.
- "why" must be at most {MAX_WHY_WORDS} words, specific to this trip rather
  than generic advice. No preamble, no restating the gadget name.
- priority must be exactly one of: essential, recommended, optional.
- "description" is one plain sentence of at most {MAX_DESCRIPTION_WORDS} words: what the
  item is and what to look for when buying one for travel. Not trip-specific.{_gender_instruction(context)}{_stops_instruction(context)}

Respond with JSON only: a single array, no prose and no markdown fences.
[
  {{"gadget": "...", "why": "...", "priority": "essential", "category": "...", "description": "..."{', "for": []' if _multi(context) else ''}}}
]
"""
