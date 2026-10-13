from app.models.context import TripContext


MIN_ITEMS = 5
MAX_ITEMS = 8

# Cards are image-led, so the reason is read as a caption rather than a
# paragraph. Shorter also means fewer output tokens, which dominate cost.
MAX_WHY_WORDS = 18


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


def build_gadget_prompt(context: TripContext) -> str:
    """Turn a trip context into a grounded request for gadget suggestions.

    Only the four descriptive fields are asked for. Provenance (origin,
    verified) and warnings are set by our own code -- the model does not get
    to declare its suggestions verified or safe.
    """
    trip = context.trip

    activities = (
        ", ".join(a.value for a in trip.activities)
        if trip.activities
        else "none specified"
    )

    conditions = (
        context.climate.summary
        if context.climate.available and context.climate.summary
        else "No weather information is available for these dates."
    )

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
Destination: {_place_label(context)}
Dates: {trip.start_date} to {trip.end_date} ({trip.duration_days} days)
Trip type: {trip.trip_type.value}
Activities: {activities}
{baggage_line}Travellers: {trip.travelers}

CONDITIONS
{conditions}

POWER
{_power_line(context)}

INSTRUCTIONS
- Recommend between {MIN_ITEMS} and {MAX_ITEMS} items.
- Base every recommendation on the trip facts above. Do not invent weather,
  voltage or plug details that are not stated.
- If a plug type is given, include the correct travel adapter and name the type.
- "why" must be at most {MAX_WHY_WORDS} words, specific to this trip rather
  than generic advice. No preamble, no restating the gadget name.
- priority must be exactly one of: essential, recommended, optional.

Respond with JSON only: a single array, no prose and no markdown fences.
[
  {{"gadget": "...", "why": "...", "priority": "essential", "category": "..."}}
]
"""
