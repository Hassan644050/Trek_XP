"""The home page, with a link preview that describes the shared trip.

WhatsApp, Facebook and Messenger show a shared link as a card built from
the page's Open Graph tags, and their crawlers do not run JavaScript. So a
link like /?to=coxs-bazar&from=2026-11-28&until=2026-12-05&types=beach
would preview as the generic home page unless the server says what it is.
This route serves index.html with those tags filled in for the trip.

Only known values make it into the card: places are resolved against the
destination list by slug and trip types against the active options, so a
crafted link cannot put arbitrary text on a preview from our domain. The
page itself reads the same parameters in the browser (startFromUrl).
"""

import hashlib
import html
import re
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from app.routes.destinations import featured, form_options, hero_images


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


def _absolute(url: str, request: Request) -> str:
    return url if url.startswith(("http://", "https://")) else str(request.base_url).rstrip("/") + url


async def _preview(request: Request) -> dict | None:
    """Title, description and image for a shared trip, or None for a plain
    visit (or a link naming no place we know)."""
    q = request.query_params
    wanted = [s for s in (q.get("to") or "").split(",") if s][:MAX_STOPS]
    if not wanted:
        return None

    places = {slugify(p.name): p for division in await featured(country=None) for p in division.places}
    stops = [(slug, places[slug]) for slug in wanted if slug in places]
    if not stops:
        return None

    names = [place.name for _, place in stops]
    title = f"Packing list for {_route_name(names)}"

    facts = []
    start, end = _date(q.get("from")), _date(q.get("until"))
    if start and end and start <= end:
        facts.append(f"{_day(start)} – {_day(end)}")
    labels = {o.value: o.label for o in (await form_options()).trip_types}
    types = [labels[t] for t in (q.get("types") or "").split(",") if t in labels]
    if types:
        facts.append(", ".join(types))
    facts.append("Checked against the weather, plugs and voltage there.")
    description = " · ".join(facts)

    heroes = {h.place_slug: h for h in await hero_images(country=None)}
    hero = heroes.get(stops[0][0]) or heroes.get("")
    image = _absolute(hero.small_url, request) if hero else None

    return {"title": title, "description": description, "image": image, "alt": hero.alt if hero else None}


def _tags(request: Request, preview: dict | None) -> str:
    p = preview or {"title": DEFAULT_TITLE, "description": DEFAULT_DESCRIPTION, "image": None, "alt": None}
    e = lambda s: html.escape(s, quote=True)  # noqa: E731
    lines = [
        "<!-- share-preview -->",
        f'<meta name="description" content="{e(p["description"])}" />',
        '<meta property="og:type" content="website" />',
        '<meta property="og:site_name" content="Trek_XP" />',
        f'<meta property="og:title" content="{e(p["title"])}" />',
        f'<meta property="og:description" content="{e(p["description"])}" />',
        # The link as shared, ref tag included: Facebook sends people to
        # og:url, so a cleaned-up URL would lose the channel it came from.
        f'<meta property="og:url" content="{e(str(request.url))}" />',
    ]
    if p["image"]:
        lines.append(f'<meta property="og:image" content="{e(p["image"])}" />')
        if p["alt"]:
            lines.append(f'<meta property="og:image:alt" content="{e(p["alt"])}" />')
        lines.append('<meta name="twitter:card" content="summary_large_image" />')
    else:
        lines.append('<meta name="twitter:card" content="summary" />')
    lines.append("<!-- /share-preview -->")
    return "\n".join(lines)


@router.get("/", include_in_schema=False)
async def home(request: Request) -> Response:
    page = INDEX.read_text(encoding="utf-8")
    preview = await _preview(request)
    body = _BLOCK.sub(lambda _: _tags(request, preview), page, count=1)

    # The page is revalidated on every visit (see main.py); an unchanged one
    # is still a cheap 304.
    etag = '"' + hashlib.sha256(body.encode()).hexdigest()[:32] + '"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return HTMLResponse(body, headers={"ETag": etag})
