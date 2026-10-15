"""Public, server-rendered gadget detail pages with search-friendly URLs.

Rendered on the server (not fetched by JS) so the content, title and
social/preview tags are in the HTML a crawler sees. One page per gadget at
/gadget/<slug>, plus an index at /gadgets for crawlability.

The layout follows the shared Trek_XP detail-page design: a two-column
hero (photo + details), a category badge, a monospace eyebrow, a tinted
"Why you need it" box, "Best for" tags, and cream section panels in the
green/amber brand palette.
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


# ---------- the shared HTML shell (detail-page design) ----------

_STYLE = """
  :root {
    --bg: oklch(0.92 0.045 150); --panel: oklch(0.985 0.012 100); --paper: #fff;
    --ink: oklch(0.26 0.03 155); --ink-soft: oklch(0.45 0.03 155); --ink-faint: oklch(0.55 0.03 155);
    --green: oklch(0.32 0.07 155); --green-mid: oklch(0.42 0.09 155);
    --badge: oklch(0.42 0.1 155); --tint: oklch(0.92 0.05 150);
    --amber: oklch(0.8 0.13 85); --line: oklch(0.84 0.03 150); --line-soft: oklch(0.88 0.02 150);
    --sans: 'Nunito', system-ui, -apple-system, 'Segoe UI', sans-serif;
    --mono: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: oklch(0.15 0.02 155); --panel: oklch(0.2 0.02 155); --paper: oklch(0.24 0.02 155);
      --ink: oklch(0.93 0.012 150); --ink-soft: oklch(0.72 0.02 150); --ink-faint: oklch(0.6 0.02 150);
      --green: oklch(0.72 0.09 155); --green-mid: oklch(0.64 0.1 155);
      --badge: oklch(0.5 0.11 155); --tint: oklch(0.28 0.04 150);
      --amber: oklch(0.8 0.13 85); --line: oklch(0.4 0.03 150); --line-soft: oklch(0.34 0.02 150);
      color-scheme: dark;
    }
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--ink); font-family: var(--sans);
    font-weight: 600; -webkit-font-smoothing: antialiased; line-height: 1.5; }
  a { color: var(--green); text-decoration: none; }
  a:hover { color: var(--green-mid); text-decoration: underline; }
  .page { max-width: none; margin: 0 auto; padding: 32px 36px 64px;
    display: flex; flex-direction: column; gap: 24px; }
  .crumb { display: flex; align-items: center; gap: 10px; font-size: 15px; font-weight: 800; flex-wrap: wrap; }
  .crumb .sep { color: var(--ink-faint); }
  .crumb .here { color: var(--ink-soft); }

  .hero { display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(0, 1fr); background: var(--panel); }
  .hero .photo { position: relative; min-height: 460px; background: var(--paper); }
  .hero .photo .badge { position: absolute; z-index: 1; top: 18px; left: 18px; font-size: 13px;
    font-weight: 900; letter-spacing: 0.08em; text-transform: uppercase; padding: 6px 12px;
    background: var(--badge); color: #fff; }
  .hero .photo img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; padding: 28px; }
  .hero .photo.empty { display: flex; align-items: center; justify-content: center;
    color: var(--ink-faint); font: 700 13px var(--mono); letter-spacing: 0.08em; text-transform: uppercase; }
  .hero .info { display: flex; flex-direction: column; gap: 22px; padding: 40px; }
  .eye { font: 700 12px var(--mono); letter-spacing: 0.12em; text-transform: uppercase; color: var(--green-mid); }
  .hero h1 { margin: 0; font-size: 44px; line-height: 1.02; font-weight: 900; letter-spacing: -0.02em; text-wrap: pretty; }
  .why { display: flex; flex-direction: column; gap: 8px; padding: 18px 20px; background: var(--tint); }
  .why .label { font-size: 13px; font-weight: 900; letter-spacing: 0.06em; text-transform: uppercase; }
  .why p { margin: 0; font-size: 17px; line-height: 1.5; font-weight: 600; text-wrap: pretty; }
  .field .label { font-size: 13px; font-weight: 900; letter-spacing: 0.06em; text-transform: uppercase; display: block; margin-bottom: 10px; }
  .tags { display: flex; gap: 8px; flex-wrap: wrap; }
  .tag { padding: 8px 14px; font-size: 14px; font-weight: 800; background: var(--paper); border: 1.5px solid var(--line); }
  a.tag { color: var(--ink); text-decoration: none; }
  a.tag:hover { border-color: var(--green); color: var(--green); text-decoration: none; }
  .cta { margin-top: auto; align-self: flex-start; padding: 16px 28px; font: 900 16px var(--sans);
    cursor: pointer; border: 2px solid var(--green); background: var(--green); color: #fff; }
  .cta:hover { text-decoration: none; }

  .panel { display: flex; flex-direction: column; gap: 18px; padding: 32px; background: var(--panel); }
  .panel h2 { margin: 0; font-size: 28px; font-weight: 900; }
  .panel .sub { font-size: 16px; color: var(--ink-soft); }
  .dest-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 16px; }
  .dest-card { display: flex; flex-direction: column; gap: 4px; padding: 20px; background: var(--paper);
    border: 2px solid var(--line-soft); }
  .dest-card:hover { border-color: var(--green); text-decoration: none; }
  .dest-card .n { font-size: 19px; font-weight: 900; color: var(--ink); }
  .dest-card .d { font-size: 14px; color: var(--ink-soft); }
  .empty { margin: 0; font-size: 16px; color: var(--ink-soft); }

  .var-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 16px; }
  .var-card { display: flex; flex-direction: column; gap: 14px; padding: 20px; text-align: left;
    background: var(--paper); border: 2px solid var(--line-soft); }
  a.var-card:hover { border-color: var(--green); text-decoration: none; }
  .var-card .top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
  .var-tier { font-size: 12px; font-weight: 900; letter-spacing: 0.08em; text-transform: uppercase; padding: 5px 10px; }
  .var-tier.budget { background: var(--line-soft); color: var(--ink); }
  .var-tier.standard { background: var(--green); color: #fff; }
  .var-tier.premium { background: var(--amber); color: oklch(0.26 0.05 155); }
  .var-card .brand { font-size: 19px; font-weight: 900; color: var(--ink); }
  .var-card .note { font-size: 14px; color: var(--ink-soft); }
  .var-card .price { font-size: 26px; font-weight: 900; letter-spacing: -0.01em; color: var(--ink); }
  .var-card .vendor { font-size: 13px; font-weight: 800; color: var(--green); }

  .idx-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 16px; }
  .idx-card { display: flex; flex-direction: column; background: var(--paper); border: 2px solid var(--line-soft); }
  .idx-card:hover { border-color: var(--green); text-decoration: none; }
  .idx-card .ph { aspect-ratio: 4 / 3; background: var(--paper); position: relative; border-bottom: 1px solid var(--line-soft); }
  .idx-card .ph img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; padding: 16px; }
  .idx-card .ph span { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
    color: var(--ink-faint); font: 700 11px var(--mono); letter-spacing: 0.08em; text-transform: uppercase; }
  .idx-card .n { padding: 14px 16px 4px; font-size: 17px; font-weight: 900; color: var(--ink); }
  .idx-card .c { padding: 0 16px 16px; font-size: 13px; color: var(--ink-soft); }

  footer { margin-top: 20px; padding-top: 18px; border-top: 1px solid var(--line-soft);
    color: var(--ink-faint); font-size: 14px; }

  @media (max-width: 760px) {
    .page { padding: 20px 16px 48px; }
    .hero { grid-template-columns: 1fr; }
    .hero .photo { min-height: 300px; }
    .hero .info { padding: 24px; }
    .hero h1 { font-size: 34px; }
    .panel { padding: 22px; }
    .panel h2 { font-size: 23px; }
  }
"""


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
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;700;800;900&family=JetBrains+Mono:wght@400;500;700&display=swap" />
{head_extra}
<style>{_STYLE}</style>
<link rel="stylesheet" href="/site-header.css" />
<script src="/site-header.js" defer></script>
</head>
<body>
<header class="site-header">
  <div class="bar">
    <a class="brand" href="/">Trek XP</a>
    <nav>
      <a class="hbtn register" href="/coordinator#register">Register</a>
      <a class="hbtn login" href="/coordinator">Login</a>
    </nav>
  </div>
</header>
<div class="page">
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
  <nav class="crumb"><a href="/">Home</a><span class="sep">/</span><span class="here">Not found</span></nav>
  <section class="panel">
    <h2>Gadget not found</h2>
    <p class="empty">That gadget is not in our catalogue. Browse all gadgets, or build a
       packing list for your trip.</p>
    <a class="cta" href="/gadgets">Browse all gadgets</a>
  </section>
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


def _type_key(name: str) -> str:
    """The kind of product a gadget is, from its name's head noun: "Sun Hat"
    and "Bucket Hat" are both "hat", "Water Shoes" and "Trekking Shoes" both
    "shoe". Used to show other gadgets of the same type, not the whole
    category. Parentheticals are dropped and a trailing plural -s stripped."""
    import re

    cleaned = re.sub(r"\([^)]*\)", " ", name)
    words = re.findall(r"[a-zA-Z]+", cleaned)
    if not words:
        return ""

    head = words[-1].lower()
    if len(head) > 3 and head.endswith("s"):
        head = head[:-1]
    return head


def _trip_types(gadget: Gadget) -> list[str]:
    values: list[str] = []
    for placement in gadget.placements:
        for value in placement.trip_types or []:
            if value not in values:
                values.append(value)
    return values


_CURRENCY_SYMBOL = {"BDT": "৳", "USD": "$", "EUR": "€", "GBP": "£", "INR": "₹"}
_QUALITY_ORDER = {"budget": 0, "standard": 1, "premium": 2}


def _price(variant) -> str:
    symbol = _CURRENCY_SYMBOL.get(variant.currency, variant.currency + " ")
    return f"{symbol}{variant.price:,}"


def _variant_card(variant) -> str:
    quality = (variant.quality or "standard").lower()
    tier_class = quality if quality in _QUALITY_ORDER else "standard"
    note_bits = [b for b in (variant.color, variant.vendor and f"from {variant.vendor}") if b]
    note = " · ".join(note_bits)
    model = f" {variant.model_name}" if variant.model_name else ""

    inner = (
        f'<div class="top"><span class="var-tier {tier_class}">{_e(quality.title())}</span>'
        + (f'<span class="vendor">View ↗</span>' if variant.url else "")
        + "</div>"
        f'<div style="display:flex;flex-direction:column;gap:4px">'
        f'<span class="brand">{_e(variant.brand)}{_e(model)}</span>'
        + (f'<span class="note">{_e(note)}</span>' if note else "")
        + "</div>"
        f'<span class="price">{_e(_price(variant))}</span>'
    )

    if variant.url:
        return (
            f'<a class="var-card" href="{_e(variant.url)}" target="_blank" rel="noopener nofollow">{inner}</a>'
        )
    return f'<div class="var-card">{inner}</div>'


def _variants_section(gadget: Gadget) -> str:
    variants = sorted(
        gadget.variants,
        key=lambda v: (_QUALITY_ORDER.get((v.quality or "").lower(), 1), v.price),
    )
    if not variants:
        return ""

    cards = "".join(_variant_card(v) for v in variants)
    return f"""
  <section class="panel">
    <h2>Buying options</h2>
    <span class="sub">The same gadget from different brands and vendors — compare price, quality and colour.</span>
    <div class="var-grid">{cards}</div>
  </section>"""


def _option_card(gadget: Gadget) -> str:
    image = _image_url(gadget.image_key)
    maker = gadget.brand or gadget.category or ""
    photo = (
        f'<div class="ph"><img src="{_e(image)}" alt="{_e(gadget.name)}" loading="lazy" /></div>'
        if image else '<div class="ph"><span>No image</span></div>'
    )
    return (
        f'<a class="idx-card" href="/gadget/{_e(gadget.slug)}">{photo}'
        f'<div class="n">{_e(gadget.name)}</div>'
        + (f'<div class="c">{_e(maker)}</div>' if maker else "")
        + "</a>"
    )


def _render_detail(request: Request, gadget: Gadget, similar: list[Gadget] | None = None) -> str:
    similar = similar or []
    canonical = _abs(request, f"/gadget/{gadget.slug}")
    image = _image_url(gadget.image_key)
    image_abs = _abs(request, image) if image else None

    maker = " ".join(filter(None, [gadget.brand, gadget.model_name]))
    eyebrow = maker or "Community-verified gear"
    description = (gadget.description or "").strip() or (
        f"{gadget.name}" + (f" by {gadget.brand}" if gadget.brand else "")
        + " — travel gear recommended by the Trek_XP community for your trip."
    )

    badge = _e(gadget.category) if gadget.category else "Gear"
    photo = (
        f'<div class="photo"><span class="badge">{badge}</span>'
        f'<img src="{_e(image)}" alt="{_e(gadget.name)}" /></div>'
        if image
        else f'<div class="photo empty"><span class="badge">{badge}</span>No image</div>'
    )

    trip_tags = "".join(
        f'<span class="tag">{_e(v.replace("_", " ").title())}</span>'
        for v in _trip_types(gadget)[:8]
    )
    best_for = (
        f'<div class="field"><span class="label">Best for</span>'
        f'<div class="tags">{trip_tags}</div></div>'
        if trip_tags else ""
    )

    # Destinations stay, as compact chips in the hero, linking to the
    # personalised home page -- the main middle section is for alternatives.
    variants_section = _variants_section(gadget)

    if similar:
        head = _type_key(gadget.name)
        heading = f"More {head.title()}s" if head else "More like this"
        cards = "".join(_option_card(g) for g in similar)
        similar_section = f"""
  <section class="panel">
    <h2>{_e(heading)}</h2>
    <span class="sub">Other {_e(head + 's' if head else 'gadgets')} in the community catalogue.</span>
    <div class="idx-grid">{cards}</div>
  </section>"""
    else:
        similar_section = ""

    body = f"""
  <nav class="crumb">
    <a href="/">Home</a><span class="sep">/</span>
    <a href="/gadgets">Gadgets</a>{f'<span class="sep">/</span><span class="here">{_e(gadget.category)}</span>' if gadget.category else ''}
    <span class="sep">/</span><span class="here">{_e(gadget.name)}</span>
  </nav>
  <section class="hero">
    {photo}
    <div class="info">
      <div style="display:flex;flex-direction:column;gap:10px">
        <span class="eye">{_e(eyebrow)}</span>
        <h1>{_e(gadget.name)}</h1>
      </div>
      <div class="why">
        <span class="label">Why you need it</span>
        <p>{_e(description)}</p>
      </div>
      {best_for}
      <a class="cta" href="/">Build your packing list →</a>
    </div>
  </section>{variants_section}{similar_section}
  <section class="panel">
    <h2>Traveler experiences</h2>
    <p class="empty">No experiences yet. Travellers who used this on a trip can share how it held
       up from their packing list.</p>
  </section>
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
        '<meta property="og:type" content="product" />'
        f'<meta property="og:title" content="{_e(gadget.name)}" />'
        f'<meta property="og:description" content="{_e(description)}" />'
        f'<meta property="og:url" content="{_e(canonical)}" />'
        '<meta property="og:site_name" content="Trek_XP" />'
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
    gadget, similar = await _load_detail(slug)

    if gadget is None:
        return _not_found(request)

    return HTMLResponse(
        _render_detail(request, gadget, similar), headers={"Cache-Control": CACHE}
    )


async def _load_detail(slug: str) -> tuple[Gadget | None, list[Gadget]]:
    """The gadget, plus other active gadgets in the same category to offer
    as alternatives. Best effort: a database problem yields nothing."""
    try:
        sessionmaker = get_sessionmaker()
    except DatabaseNotConfiguredException:
        return None, []

    try:
        async with sessionmaker() as db:
            gadget = await db.scalar(
                select(Gadget)
                .where(Gadget.slug == slug, Gadget.is_active.is_(True))
                .options(
                    selectinload(Gadget.placements).joinedload(Placement.place),
                    selectinload(Gadget.variants),
                )
            )
            if gadget is None:
                return None, []

            similar: list[Gadget] = []
            head = _type_key(gadget.name)
            if head:
                # Prefilter in SQL on the head word, then keep only exact
                # same-type matches (so "Sun Hat" finds other hats, not
                # everything in the Protection category).
                candidates = (
                    await db.scalars(
                        select(Gadget)
                        .where(
                            Gadget.id != gadget.id,
                            Gadget.is_active.is_(True),
                            Gadget.slug.is_not(None),
                            Gadget.name.ilike(f"%{head}%"),
                        )
                        .order_by(Gadget.name)
                        .limit(24)
                    )
                ).all()
                similar = [g for g in candidates if _type_key(g.name) == head][:6]
            return gadget, similar
    except SQLAlchemyError:
        logger.warning("Gadget detail lookup failed for %r", slug, exc_info=True)
        return None, []


# ---------- index page ----------


@router.get("/gadgets", response_class=HTMLResponse, include_in_schema=False)
async def gadget_index(request: Request) -> HTMLResponse:
    gadgets = await _load_active_gadgets()

    cards = "".join(
        f'<a class="idx-card" href="/gadget/{_e(g.slug)}">'
        + (
            f'<div class="ph"><img src="{_e(_image_url(g.image_key))}" alt="{_e(g.name)}" loading="lazy" /></div>'
            if g.image_key else '<div class="ph"><span>No image</span></div>'
        )
        + f'<div class="n">{_e(g.name)}</div>'
        + (f'<div class="c">{_e(g.category)}</div>' if g.category else "")
        + "</a>"
        for g in gadgets
    ) or '<p class="empty">No gadgets in the catalogue yet.</p>'

    body = f"""
  <nav class="crumb"><a href="/">Home</a><span class="sep">/</span><span class="here">Gadgets</span></nav>
  <section class="panel">
    <h2>Travel gadgets</h2>
    <span class="sub">Community-verified gear, recommended per destination. {len(gadgets)} in the catalogue.</span>
    <div class="idx-grid">{cards}</div>
  </section>
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
