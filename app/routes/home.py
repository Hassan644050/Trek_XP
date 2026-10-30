"""The home page's link preview, and the card image a shared list shows.

WhatsApp, Facebook and Messenger show a shared link as a card built from
the page's Open Graph tags, and their crawlers do not run JavaScript. So a
link like /?to=coxs-bazar&from=2026-11-28&until=2026-12-05&types=beach
would preview as the generic home page unless the server says what it is.

- `/` serves index.html with those tags filled in for the trip.
- `/share/card.png` draws the picture they point to: the trip and its top
  gadgets (services/share_card.py). The gadgets come from the quick list --
  verified items plus any cached model ones -- so a card never waits on,
  or spends, a model call.

Only known values make it into either: places are resolved against the
destination list by slug, trip types and activities against the active
options, dates must parse. A crafted link cannot put its own text on a
preview from our domain. The page reads the same parameters in the
browser (applySharedTrip in index.html).
"""

import asyncio
import hashlib
import html
import logging
import re
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import HTMLResponse, Response

from app.models.trip import MAX_TRIP_TYPES, TripRequest
from app.routes.destinations import featured, form_options
from app.routes.recommend import recommend
from app.services.media.storage import get_image_storage, variant_key
from app.services.media.variants import THUMB
from app.services.share_card import HEIGHT, WIDTH, Card, CardItem, order_items, render


logger = logging.getLogger(__name__)

router = APIRouter()

INDEX = Path(__file__).resolve().parents[1] / "static" / "index.html"
MAX_STOPS = 5

DEFAULT_TITLE = "Trek_XP — What should you actually pack?"
DEFAULT_DESCRIPTION = (
    "Pick a place in Bangladesh, set your dates, and get a packing list "
    "checked against the weather, plug type and voltage there."
)

_BLOCK = re.compile(r"<!-- share-preview -->.*?<!-- /share-preview -->", re.S)


def slugify(name: str) -> str:
    """The home page's slug rule (slugify in index.html) -- they must agree."""
    slug = re.sub(r"[’']", "", name.lower())
    return re.sub(r"[^a-z0-9]+", "-", slug).strip("-")


def _date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _day(d: date) -> str:
    return f"{d.day} {d.strftime('%b')}"


def _route_name(names: list[str]) -> str:
    if len(names) <= 2:
        return " + ".join(names)
    return f"{names[0]} + {len(names) - 1} more"


def _absolute(path: str, request: Request) -> str:
    return str(request.base_url).rstrip("/") + path


# ---------- the trip in a shared link ----------


@dataclass
class SharedTrip:
    places: list  # FeaturedPlace, in route order
    start: date | None = None
    end: date | None = None
    types: list[tuple[str, str]] = field(default_factory=list)   # (value, label)
    acts: list[tuple[str, str]] = field(default_factory=list)
    pax: int | None = None
    who: str | None = None

    @property
    def name(self) -> str:
        return _route_name([p.name for p in self.places])

    def query(self) -> str:
        """The trip as a canonical query string -- the same trip always
        gives the same card URL (and cache entry), however it was written."""
        params = {"to": ",".join(slugify(p.name) for p in self.places)}
        if self.start and self.end:
            params |= {"from": self.start.isoformat(), "until": self.end.isoformat()}
        if self.types:
            params["types"] = ",".join(v for v, _ in self.types)
        if self.acts:
            params["acts"] = ",".join(v for v, _ in self.acts)
        if self.pax:
            params["pax"] = str(self.pax)
        if self.who:
            params["who"] = self.who
        return urlencode(params, safe=",")


async def _shared_trip(request: Request) -> SharedTrip | None:
    """The trip a link describes, or None if it names no place we know."""
    q = request.query_params
    wanted = [s for s in (q.get("to") or "").split(",") if s][:MAX_STOPS]
    if not wanted:
        return None

    known = {slugify(p.name): p for division in await featured(country=None) for p in division.places}
    places = [known[s] for s in dict.fromkeys(wanted) if s in known]
    if not places:
        return None

    trip = SharedTrip(places=places)
    start, end = _date(q.get("from")), _date(q.get("until"))
    if start and end and start <= end <= start + timedelta(days=90):
        trip.start, trip.end = start, end

    options = await form_options()
    type_labels = {o.value: o.label for o in options.trip_types}
    act_labels = {o.value: o.label for o in options.activities}
    trip.types = [(t, type_labels[t]) for t in dict.fromkeys((q.get("types") or "").split(",")) if t in type_labels]
    trip.types = trip.types[:MAX_TRIP_TYPES]
    trip.acts = [(a, act_labels[a]) for a in dict.fromkeys((q.get("acts") or "").split(",")) if a in act_labels]
    trip.acts = trip.acts[:12]
    if (q.get("pax") or "").isdigit() and 1 <= int(q["pax"]) <= 50:
        trip.pax = int(q["pax"])
    if q.get("who") in ("female", "male", "mixed"):
        trip.who = q["who"]
    return trip


# ---------- the page ----------


def _tags(request: Request, trip: SharedTrip | None) -> str:
    e = lambda s: html.escape(s, quote=True)  # noqa: E731
    if trip:
        title = f"Packing list for {trip.name}"
        facts = []
        if trip.start and trip.end:
            facts.append(f"{_day(trip.start)} – {_day(trip.end)}")
        if trip.types:
            facts.append(", ".join(label for _, label in trip.types))
        facts.append("Checked against the weather, plugs and voltage there.")
        description = " · ".join(facts)
    else:
        title, description = DEFAULT_TITLE, DEFAULT_DESCRIPTION

    lines = [
        "<!-- share-preview -->",
        f'<meta name="description" content="{e(description)}" />',
        '<meta property="og:type" content="website" />',
        '<meta property="og:site_name" content="Trek_XP" />',
        f'<meta property="og:title" content="{e(title)}" />',
        f'<meta property="og:description" content="{e(description)}" />',
        # The link as shared, ref tag included: Facebook sends people to
        # og:url, so a cleaned-up URL would lose the channel it came from.
        f'<meta property="og:url" content="{e(str(request.url))}" />',
    ]
    if trip:
        card = _absolute(f"/share/card.png?{trip.query()}", request)
        lines += [
            f'<meta property="og:image" content="{e(card)}" />',
            '<meta property="og:image:type" content="image/png" />',
            f'<meta property="og:image:width" content="{WIDTH}" />',
            f'<meta property="og:image:height" content="{HEIGHT}" />',
            f'<meta property="og:image:alt" content="{e(title)}: the gadgets to pack" />',
            '<meta name="twitter:card" content="summary_large_image" />',
        ]
    else:
        lines.append('<meta name="twitter:card" content="summary" />')
    lines.append("<!-- /share-preview -->")
    return "\n".join(lines)


@router.get("/", include_in_schema=False)
async def home(request: Request) -> Response:
    page = INDEX.read_text(encoding="utf-8")
    trip = await _shared_trip(request)
    body = _BLOCK.sub(lambda _: _tags(request, trip), page, count=1)

    # The page is revalidated on every visit (see main.py); an unchanged one
    # is still a cheap 304.
    etag = '"' + hashlib.sha256(body.encode()).hexdigest()[:32] + '"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return HTMLResponse(body, headers={"ETag": etag})


# ---------- the card image ----------

# Drawn cards, by canonical trip query. A crawler asks again for every share
# of the same list, and the share button warms the entry before it does.
CARD_TTL_SECONDS = 60 * 60
# A card drawn without its gadgets (the list failed to load) is retried soon.
PARTIAL_CARD_TTL_SECONDS = 5 * 60
MAX_CARDS = 256
_cards: OrderedDict[str, tuple[float, bytes]] = OrderedDict()


def _trip_request(trip: SharedTrip) -> TripRequest:
    start = trip.start or date.today() + timedelta(days=30)
    end = trip.end or start + timedelta(days=7)
    common = dict(
        start_date=start, end_date=end,
        trip_types=[v for v, _ in trip.types] or ["beach"],
        activities=[v for v, _ in trip.acts],
        travelers=trip.pax or 2, gender=trip.who,
    )
    if len(trip.places) == 1:
        p = trip.places[0]
        return TripRequest(destination=p.name, latitude=p.latitude, longitude=p.longitude,
                           country_code=p.country_code, country_name=p.country_name, **common)
    return TripRequest(stops=[
        dict(name=p.name, latitude=p.latitude, longitude=p.longitude,
             country_code=p.country_code, country_name=p.country_name)
        for p in trip.places
    ], **common)


def _conditions(answer) -> list[str]:
    stops = answer.stops or []
    known = [s for s in stops if s.climate_available and s.min_temp_c is not None]
    lines = []
    if known:
        lo = round(min(s.min_temp_c for s in known))
        hi = round(max(s.max_temp_c for s in known))
        lines.append(f"{lo}–{hi}°C")
    plug = next((s for s in stops if s.plug_types), None)
    if plug:
        lines.append(f"Plug {'/'.join(plug.plug_types)} · {plug.voltage}")
    return lines


async def _load_thumbnails(items: list[CardItem]) -> None:
    """Read the shown gadgets' thumbnails, side by side. A photo that cannot
    be read is just left out -- the row shows the gadget's initial."""
    storage = get_image_storage()

    async def load(item: CardItem) -> None:
        try:
            item.image = await asyncio.to_thread(storage.read, variant_key(item.image_key, THUMB.name))
        except Exception:
            logger.warning("Share card: no thumbnail for %r", item.name, exc_info=True)

    await asyncio.gather(*(load(i) for i in items if i.image_key))


async def _card_for(trip: SharedTrip | None) -> tuple[Card, bool]:
    """The card, and whether it is complete (its gadget list loaded)."""
    if trip is None:
        return Card(places="Your next trip", trip="Bangladesh"), True

    card = Card(places=trip.name)
    labels = [label for _, label in trip.types] + [label for _, label in trip.acts]
    card.trip = " · ".join(labels[:4]) or None
    if trip.start and trip.end:
        days = (trip.end - trip.start).days + 1
        card.dates = f"{_day(trip.start)} – {_day(trip.end)} · {days} day{'s' if days != 1 else ''}"

    # The list itself is best effort: without it the card still names the
    # trip, and a crawler never gets an error.
    try:
        answer = await recommend(_trip_request(trip), BackgroundTasks(), quick=True)
        items = [CardItem(r.gadget, r.priority.value, image_key=r.image_key) for r in answer.recommendations]
        card.items = order_items(items)
        card.total = len(items)
        await _load_thumbnails(card.items)
        card.conditions = _conditions(answer)
    except Exception:
        logger.warning("Share card: could not load the list", exc_info=True)
        return card, False
    return card, True


@router.get("/share/card.png", include_in_schema=False)
async def share_card(request: Request) -> Response:
    trip = await _shared_trip(request)
    key = trip.query() if trip else ""

    hit = _cards.get(key)
    if hit and time.monotonic() < hit[0]:
        png = hit[1]
    else:
        card, complete = await _card_for(trip)
        png = await asyncio.to_thread(render, card)  # Pillow is CPU work
        ttl = CARD_TTL_SECONDS if complete else PARTIAL_CARD_TTL_SECONDS
        _cards[key] = (time.monotonic() + ttl, png)  # (expires at, image)
        _cards.move_to_end(key)
        while len(_cards) > MAX_CARDS:
            _cards.popitem(last=False)

    return Response(png, media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})
