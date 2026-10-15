"""Public, server-rendered gadget detail pages with search-friendly URLs.

Rendered on the server (not fetched by JS) so the content, title and
social/preview tags are in the HTML a crawler sees. One page per gadget at
/gadget/<slug>, plus an index at /gadgets for crawlability.
"""

import html
import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload, selectinload

from app.db.engine import get_sessionmaker
from app.db.models import Gadget, Placement
from app.exceptions.exceptions import DatabaseNotConfiguredException
from app.services.media.storage import get_image_storage, variant_key
from app.services.media.variants import DETAIL
from app.services.slug import url_slug


logger = logging.getLogger(__name__)

router = APIRouter(tags=["public-pages"])

CACHE = "public, max-age=300"


def _e(value) -> str:
    return html.escape(str(value), quote=True)


def _abs(request: Request, url: str) -> str:
    if not url or url.startswith("http"):
        return url
    return str(request.base_url).rstrip("/") + url


def _json_ld(obj) -> str:
    """JSON safe to embed in an HTML <script> block: the angle brackets and
    ampersand are escaped so user content cannot break out of the tag."""
    return (
        json.dumps(obj)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def _image_url(image_key: str | None) -> str | None:
    if not image_key:
        return None
    return get_image_storage().url(variant_key(image_key, DETAIL.name))


# ---------- the shared HTML shell ----------


def _shell(*, title: str, description: str, canonical: str, head_extra: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{_e(title)}</title>
<meta name="description" content="{_e(description)}" />
<link rel="canonical" href="{_e(canonical)}" />
<link rel="icon" href="/favicon.ico" sizes="any" />
<link rel="apple-touch-icon" href="/apple-touch-icon.png" />
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Nunito:wght@400;700;800;900&display=swap" />
{head_extra}
<style>
  :root {{
    --green: #1f6b4a; --green-deep: #184f38; --amber: #c98a1e;
    --ink: #1a2420; --ink-soft: #4a5a52; --line: #d8e0db;
    --surface: #f4f6f4; --paper: #ffffff;
    --sans: 'Nunito', system-ui, -apple-system, 'Segoe UI', sans-serif;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --green: #58c48d; --green-deep: #3f9d6e; --amber: #e0a73c;
      --ink: #e7efe9; --ink-soft: #a7b6ae; --line: #2b3832;
      --surface: #131a16; --paper: #1b231e;
      color-scheme: dark;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: var(--surface); color: var(--ink);
    font-family: var(--sans); font-weight: 600; line-height: 1.6; }}
  a {{ color: var(--green-deep); }}
  @media (prefers-color-scheme: dark) {{ a {{ color: var(--green); }} }}
  .wrap {{ max-width: 920px; margin: 0 auto; padding: 24px 20px 64px; }}
  .top {{ display: flex; align-items: center; gap: 10px; padding-bottom: 20px; }}
  .top .mark {{ font-weight: 900; font-size: 20px; letter-spacing: -0.02em; }}
  .top .mark span {{ color: var(--green); }}
  nav.crumb {{ font-size: 13px; color: var(--ink-soft); margin-bottom: 18px; }}
  nav.crumb a {{ text-decoration: none; }}
  h1 {{ font-size: clamp(1.8rem, 5vw, 2.6rem); font-weight: 900; letter-spacing: -0.03em;
    line-height: 1.1; margin: 0 0 8px; text-wrap: balance; }}
  .sub {{ color: var(--ink-soft); font-size: 1.05rem; margin: 0 0 20px; }}
  .card {{ background: var(--paper); border: 1px solid var(--line); }}
  .hero {{ display: grid; grid-template-columns: minmax(0, 320px) minmax(0, 1fr); gap: 0; overflow: hidden; }}
  .hero .photo {{ aspect-ratio: 4 / 3; background: var(--surface); display: flex; }}
  .hero .photo img {{ width: 100%; height: 100%; object-fit: contain; padding: 18px; }}
  .hero .photo.empty {{ align-items: center; justify-content: center; color: var(--ink-soft);
    font-size: 13px; text-transform: uppercase; letter-spacing: 0.08em; }}
  .hero .body {{ padding: 22px 24px; display: flex; flex-direction: column; gap: 10px; }}
  .tags {{ display: flex; flex-wrap: wrap; gap: 8px; }}
  .tag {{ font-size: 12px; font-weight: 800; text-transform: uppercase; letter-spacing: 0.05em;
    padding: 4px 9px; border: 1px solid var(--line); color: var(--ink-soft); }}
  .tag.cat {{ background: var(--green); color: #fff; border-color: var(--green); }}
  .desc {{ margin: 6px 0 0; color: var(--ink); font-weight: 600; }}
  section.block {{ margin-top: 32px; }}
  section.block h2 {{ font-size: 1.1rem; font-weight: 900; letter-spacing: -0.01em; margin: 0 0 12px; }}
  ul.dests {{ list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: 8px; }}
  ul.dests a {{ display: inline-block; text-decoration: none; padding: 8px 13px;
    background: var(--paper); border: 1px solid var(--line); font-weight: 700; }}
  ul.dests a:hover {{ border-color: var(--green); }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 14px; }}
  .grid a {{ display: flex; flex-direction: column; text-decoration: none; color: inherit;
    background: var(--paper); border: 1px solid var(--line); }}
  .grid a:hover {{ border-color: var(--green); }}
  .grid .ph {{ aspect-ratio: 4 / 3; background: var(--surface); display: flex;
    align-items: center; justify-content: center; }}
  .grid .ph img {{ width: 100%; height: 100%; object-fit: contain; padding: 12px; }}
  .grid .ph span {{ color: var(--ink-soft); font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; }}
  .grid .n {{ padding: 10px 12px; font-weight: 800; }}
  .grid .c {{ padding: 0 12px 12px; color: var(--ink-soft); font-size: 13px; font-weight: 600; }}
  .cta {{ display: inline-block; margin-top: 26px; background: var(--green); color: #fff;
    text-decoration: none; font-weight: 800; padding: 12px 20px; }}
  footer {{ margin-top: 48px; padding-top: 18px; border-top: 1px solid var(--line);
    color: var(--ink-soft); font-size: 13px; }}
  @media (max-width: 640px) {{ .hero {{ grid-template-columns: 1fr; }} }}
</style>
</head>
<body>
<div class="wrap">
  <div class="top"><span class="mark">Trek<span>_XP</span></span></div>
{body}
  <footer>
    <a href="/gadgets">All gadgets</a> · <a href="/">Build your packing list</a> ·
    Community-verified travel gear.
  </footer>
</div>
</body>
</html>
"""


def _not_found(request: Request) -> HTMLResponse:
    body = """
  <nav class="crumb"><a href="/">Home</a> · <a href="/gadgets">Gadgets</a></nav>
  <h1>Gadget not found</h1>
  <p class="sub">That gadget is not in our catalogue. Browse all gadgets, or build a
     packing list for your trip.</p>
  <a class="cta" href="/gadgets">Browse all gadgets</a>
"""
    html_text = _shell(
        title="Gadget not found — Trek_XP",
        description="This gadget is not in the Trek_XP catalogue.",
        canonical=_abs(request, "/gadgets"),
        head_extra='<meta name="robots" content="noindex" />',
        body=body,
    )
    return HTMLResponse(html_text, status_code=404)


# ---------- detail page ----------


def _destinations(gadget: Gadget) -> list[tuple[str, str]]:
    """Unique (place name, division) for the places this gadget is placed at."""
    seen: dict[str, tuple[str, str]] = {}
    for placement in gadget.placements:
        place = placement.place
        if place.name not in seen:
            seen[place.name] = (place.name, place.division or "")
    return sorted(seen.values())


def _trip_types(gadget: Gadget) -> list[str]:
    values: list[str] = []
    for placement in gadget.placements:
        for value in placement.trip_types or []:
            if value not in values:
                values.append(value)
    return values


def _render_detail(request: Request, gadget: Gadget) -> str:
    canonical = _abs(request, f"/gadget/{gadget.slug}")
    image = _image_url(gadget.image_key)
    image_abs = _abs(request, image) if image else None

    maker = " ".join(filter(None, [gadget.brand, gadget.model_name]))
    description = (gadget.description or "").strip() or (
        f"{gadget.name}" + (f" by {gadget.brand}" if gadget.brand else "")
        + " — travel gear recommended by the Trek_XP community for your trip."
    )

    tags = []
    if gadget.category:
        tags.append(f'<span class="tag cat">{_e(gadget.category)}</span>')
    if gadget.color:
        tags.append(f'<span class="tag">{_e(gadget.color)}</span>')
    for value in _trip_types(gadget)[:6]:
        tags.append(f'<span class="tag">{_e(value.replace("_", " "))}</span>')

    photo = (
        f'<div class="photo"><img src="{_e(image)}" alt="{_e(gadget.name)}" /></div>'
        if image else '<div class="photo empty">No image</div>'
    )

    dests = _destinations(gadget)
    if dests:
        items = "".join(
            f'<li><a href="/?to={_e(url_slug(name))}">{_e(name)}'
            + (f' <span style="color:var(--ink-soft);font-weight:600">· {_e(div)}</span>' if div else "")
            + "</a></li>"
            for name, div in dests
        )
        dest_block = f"""
  <section class="block">
    <h2>Recommended for these destinations</h2>
    <ul class="dests">{items}</ul>
  </section>"""
    else:
        dest_block = ""

    body = f"""
  <nav class="crumb"><a href="/">Home</a> · <a href="/gadgets">Gadgets</a> · {_e(gadget.name)}</nav>
  <div class="card hero">
    {photo}
    <div class="body">
      <h1>{_e(gadget.name)}</h1>
      {f'<p class="sub">{_e(maker)}</p>' if maker else ''}
      <div class="tags">{''.join(tags)}</div>
      <p class="desc">{_e(description)}</p>
    </div>
  </div>{dest_block}
  <a class="cta" href="/">Build your packing list →</a>
"""

    product = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": gadget.name,
        "description": description,
        "url": canonical,
    }
    if image_abs:
        product["image"] = [image_abs]
    if gadget.category:
        product["category"] = gadget.category
    if gadget.brand:
        product["brand"] = {"@type": "Brand", "name": gadget.brand}
    if gadget.color:
        product["color"] = gadget.color

    og_image = (
        f'<meta property="og:image" content="{_e(image_abs)}" />'
        '<meta name="twitter:card" content="summary_large_image" />'
        if image_abs else '<meta name="twitter:card" content="summary" />'
    )
    head_extra = (
        f'<meta property="og:type" content="product" />'
        f'<meta property="og:title" content="{_e(gadget.name)}" />'
        f'<meta property="og:description" content="{_e(description)}" />'
        f'<meta property="og:url" content="{_e(canonical)}" />'
        f'<meta property="og:site_name" content="Trek_XP" />'
        f'{og_image}'
        f'<script type="application/ld+json">{_json_ld(product)}</script>'
    )

    title_suffix = f" by {gadget.brand}" if gadget.brand else ""
    return _shell(
        title=f"{gadget.name}{title_suffix} — Trek_XP",
        description=description[:300],
        canonical=canonical,
        head_extra=head_extra,
        body=body,
    )


@router.get("/gadget/{slug}", response_class=HTMLResponse, include_in_schema=False)
async def gadget_detail(slug: str, request: Request) -> HTMLResponse:
    gadget = await _load_by_slug(slug)

    if gadget is None:
        return _not_found(request)

    return HTMLResponse(_render_detail(request, gadget), headers={"Cache-Control": CACHE})


async def _load_by_slug(slug: str) -> Gadget | None:
    try:
        sessionmaker = get_sessionmaker()
    except DatabaseNotConfiguredException:
        return None

    try:
        async with sessionmaker() as db:
            return await db.scalar(
                select(Gadget)
                .where(Gadget.slug == slug, Gadget.is_active.is_(True))
                .options(selectinload(Gadget.placements).joinedload(Placement.place))
            )
    except SQLAlchemyError:
        logger.warning("Gadget detail lookup failed for %r", slug, exc_info=True)
        return None


# ---------- index page ----------


@router.get("/gadgets", response_class=HTMLResponse, include_in_schema=False)
async def gadget_index(request: Request) -> HTMLResponse:
    gadgets = await _load_active_gadgets()

    cards = "".join(
        f'<a href="/gadget/{_e(g.slug)}">'
        + (
            f'<div class="ph"><img src="{_e(_image_url(g.image_key))}" alt="{_e(g.name)}" loading="lazy" /></div>'
            if g.image_key else '<div class="ph"><span>No image</span></div>'
        )
        + f'<div class="n">{_e(g.name)}</div>'
        + (f'<div class="c">{_e(g.category)}</div>' if g.category else "")
        + "</a>"
        for g in gadgets
    ) or '<p class="sub">No gadgets in the catalogue yet.</p>'

    body = f"""
  <nav class="crumb"><a href="/">Home</a> · Gadgets</nav>
  <h1>Travel gadgets</h1>
  <p class="sub">Community-verified gear, recommended per destination. {len(gadgets)} in the catalogue.</p>
  <div class="grid">{cards}</div>
  <a class="cta" href="/">Build your packing list →</a>
"""
    html_text = _shell(
        title="Travel gadgets — Trek_XP",
        description="Browse community-verified travel gadgets recommended for destinations across Bangladesh.",
        canonical=_abs(request, "/gadgets"),
        head_extra='<meta property="og:type" content="website" /><meta property="og:title" content="Travel gadgets — Trek_XP" />',
        body=body,
    )
    return HTMLResponse(html_text, headers={"Cache-Control": CACHE})


async def _load_active_gadgets() -> list[Gadget]:
    try:
        sessionmaker = get_sessionmaker()
    except DatabaseNotConfiguredException:
        return []

    try:
        async with sessionmaker() as db:
            return list(
                (
                    await db.scalars(
                        select(Gadget)
                        .where(Gadget.is_active.is_(True), Gadget.slug.is_not(None))
                        .order_by(Gadget.name)
                    )
                ).all()
            )
    except SQLAlchemyError:
        logger.warning("Gadget index lookup failed", exc_info=True)
        return []
