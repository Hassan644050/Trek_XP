"""Saved bags: keep a bag for later, or share it.

- POST /api/bags                  save the bag the browser holds -> /bag/<code>
- GET  /bag/<code>                the saved bag: today's names, prices, stock,
                                  "Add all to my bag", share buttons
- GET  /share/bag/<code>.png      its preview card for WhatsApp / Facebook

The logic lives in services/bags.py; the page reuses the gadget pages'
shell and styles.
"""

import asyncio
import html
import json
import re
import time
from collections import OrderedDict, defaultdict, deque

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import check_csrf
from app.db.engine import get_db
from app.exceptions.exceptions import TooManyRequestsException
from app.models.bags import BagView, SaveBagIn, SavedBagOut
from app.routes.gadget_pages import _not_found, _shell
from app.routes.home import _load_thumbnails
from app.services import bags as bag_service
from app.services.analytics import is_bot
from app.services.share_card import CARD_VERSION, HEIGHT, WIDTH, Card, CardItem, order_items, render


router = APIRouter()

CODE = re.compile(r"[a-z2-9]{6}")
SAVES_PER_HOUR = 20
_recent: dict[str, deque] = defaultdict(deque)
_SYMBOL = {"BDT": "৳", "USD": "$", "EUR": "€", "GBP": "£", "INR": "₹"}


def _e(value) -> str:
    return html.escape(str(value), quote=True)


def _money(amount: int, currency: str) -> str:
    return f"{_SYMBOL.get(currency, currency + ' ')}{amount:,}"


def _rate_limit(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    seen = _recent[ip]
    while seen and now - seen[0] > 3600:
        seen.popleft()
    if len(seen) >= SAVES_PER_HOUR:
        raise TooManyRequestsException("Too many saved bags from this connection. Please try again later.")
    seen.append(now)


@router.post("/api/bags", response_model=SavedBagOut, status_code=201)
async def save_bag(payload: SaveBagIn, request: Request, db: AsyncSession = Depends(get_db)) -> SavedBagOut:
    check_csrf(request)  # same-site only
    _rate_limit(request)
    bag = await bag_service.save(db, payload)
    return SavedBagOut(code=bag.code, url=f"/bag/{bag.code}", count=len(bag.items))


# ---------- the page ----------


def _option_text(o) -> str:
    name = " ".join(p for p in (o.brand, o.model_name) if p)
    return " · ".join(p for p in (name, o.color, o.quality) if p)


def _bag_item_json(item) -> dict:
    """The item in the shape bag.js keeps (TrekBag.add)."""
    variant = None
    if item.option:
        o = item.option
        variant = {"id": o.id, "brand": o.brand, "model_name": o.model_name, "color": o.color,
                   "quality": o.quality, "price": o.price, "currency": o.currency, "vendor": o.vendor}
    return {"name": item.name, "page_url": f"/gadget/{item.slug}" if item.slug else None,
            "image_url": item.image_url, "category": item.category, "priority": item.priority,
            "variant": variant}


def _row(item) -> str:
    pic = (f'<img src="{_e(item.image_url)}" alt="" loading="lazy" />' if item.image_url
           else f'<span>{_e(item.name.strip()[:1].upper())}</span>')
    if item.slug:
        title = f'<a class="sb-name" href="/gadget/{_e(item.slug)}">{_e(item.name)}</a>'
        links = (f'<a href="/compare/{_e(item.slug)}">Compare options</a>'
                 f'<a href="/gadget/{_e(item.slug)}">Gadget details</a>')
    else:
        # Kept by name only (not in the catalog): plain text, no links.
        title = f'<span class="sb-name">{_e(item.name)}</span>'
        links = '<span class="sb-muted">Not in our catalog yet</span>'
    option = ""
    if item.option:
        o = item.option
        option = (f'<div class="sb-opt"><span>{_e(_option_text(o))}{" · " + _e(o.vendor) if o.vendor else ""}</span>'
                  f'<b>{_e(_money(o.price, o.currency))}</b>'
                  f'<span class="stock {_e(o.stock)}">{_e(o.stock_label)}</span></div>')
    elif item.slug:
        option = '<div class="sb-muted">No buying option chosen</div>'
    priority = (f'<span class="sb-pri {_e(item.priority)}">{_e(item.priority.title())}</span>'
                if item.priority else "")
    return (f'<li class="sb-item"><div class="sb-pic">{pic}</div><div class="sb-body">'
            f'<div class="sb-top">{title}{priority}</div>{option}<div class="sb-links">{links}</div></div></li>')


_STYLE = """
  .sb-list { display: flex; flex-direction: column; list-style: none; margin: 0; padding: 0; }
  .sb-item { display: grid; grid-template-columns: 72px minmax(0, 1fr); gap: 16px; padding: 16px 0;
    border-top: 1px solid var(--line-soft); }
  .sb-item:first-child { border-top: 0; }
  .sb-pic { width: 72px; height: 72px; background: var(--paper); border: 1px solid var(--line); display: flex;
    align-items: center; justify-content: center; overflow: hidden; }
  .sb-pic img { width: 100%; height: 100%; object-fit: contain; }
  .sb-pic span { color: var(--green); font-size: 28px; font-weight: 900; }
  .sb-body { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
  .sb-top { display: flex; align-items: center; flex-wrap: wrap; gap: 8px 10px; }
  .sb-name { font-size: 18px; font-weight: 900; color: var(--ink); }
  .sb-pri { font: 700 11px var(--mono); letter-spacing: 0.06em; text-transform: uppercase; padding: 2px 8px;
    background: var(--tint); color: var(--green); }
  .sb-opt { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 12px; color: var(--ink-soft); font-size: 15px; }
  .sb-opt b { color: var(--ink); }
  .sb-links { display: flex; flex-wrap: wrap; gap: 14px; font-size: 14px; font-weight: 800; }
  .sb-muted { color: var(--ink-faint); font-size: 14px; }
  .sb-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
  .sb-add { background: var(--amber); border: 0; color: oklch(0.22 0.04 155); cursor: pointer;
    font: 900 16px var(--sans); padding: 13px 20px; }
  .sb-share { display: flex; flex-wrap: wrap; gap: 8px; }
  .sb-share button { background: var(--paper); border: 1.5px solid var(--line); color: var(--ink); cursor: pointer;
    font: 800 14px var(--sans); min-height: 40px; padding: 0 14px; }
  .sb-share button:hover { border-color: var(--green); }
  .sb-total { border-top: 2px solid var(--line); display: flex; justify-content: space-between; font-size: 18px;
    font-weight: 900; padding-top: 12px; }
  .stock { font-size: 12.5px; font-weight: 800; padding: 1px 8px; }
  .stock.in { background: var(--tint); color: var(--green); }
  .stock.low { background: oklch(0.95 0.05 85); color: oklch(0.45 0.1 60); }
  .stock.out { background: oklch(0.95 0.03 25); color: oklch(0.5 0.17 25); }
"""


def _render(request: Request, view: BagView) -> str:
    n = len(view.items)
    title = f"Travel bag · {n} gadget{'s' if n != 1 else ''}"
    # The preview text names catalog gadgets only: other names came from a browser.
    known = [i.name for i in view.items if i.slug]
    listed = ", ".join(known[:5]) + (f" and {n - min(len(known), 5)} more" if n > min(len(known), 5) else "")
    description = (f"A saved travel bag on Trek_XP: {listed}." if known
                   else "A saved travel bag on Trek_XP.")
    base = str(request.base_url).rstrip("/")
    card = f"{base}/share/bag/{view.code}.png?v={CARD_VERSION}"
    head = f"""<meta name="robots" content="noindex" />
<meta property="og:type" content="website" />
<meta property="og:site_name" content="Trek_XP" />
<meta property="og:title" content="{_e(title)}" />
<meta property="og:description" content="{_e(description)}" />
<meta property="og:url" content="{_e(str(request.url))}" />
<meta property="og:image" content="{_e(card)}" />
<meta property="og:image:width" content="{WIDTH}" /><meta property="og:image:height" content="{HEIGHT}" />
<meta property="og:image:alt" content="{_e(title)}" />
<meta name="twitter:card" content="summary_large_image" />
<style>{_STYLE}</style>
<script src="/saved-bag.js" defer></script>"""
    total = (f'<div class="sb-total"><span>Chosen options</span><span>{_e(_money(view.chosen_total, view.currency))}</span></div>'
             if view.chosen_total else "")
    data = _e(json.dumps([_bag_item_json(i) for i in view.items]))
    body = f"""
  <nav class="crumb" aria-label="Breadcrumb">
    <a href="/">Home</a><span class="sep">/</span><span class="here">Saved bag</span>
  </nav>
  <section class="panel">
    <span class="eye">Saved bag</span>
    <h1 class="cmp-title">{_e(title)}</h1>
    <p class="sub">Names, prices and stock are as of today. Add it to your bag to buy, change options or keep packing.</p>
    <div class="sb-actions">
      <button type="button" class="sb-add" data-bag-import="{data}">Add all to my bag</button>
      <div class="sb-share" data-share-bag data-code="{_e(view.code)}" data-title="{_e(title)}">
        <button type="button" data-share="native" hidden>Share…</button>
        <button type="button" data-share="wa">WhatsApp</button>
        <button type="button" data-share="fb">Facebook</button>
        <button type="button" data-share="ms" hidden>Messenger</button>
        <button type="button" data-share="copy">Copy link</button>
      </div>
    </div>
    <ul class="sb-list">{"".join(_row(i) for i in view.items)}</ul>
    {total}
  </section>"""
    return _shell(title=f"{title} — Trek_XP", description=description,
                  canonical=f"{base}/bag/{view.code}", head_extra=head, body=body)


@router.get("/bag/{code}", response_class=HTMLResponse, include_in_schema=False)
async def saved_bag_page(code: str, request: Request, db: AsyncSession = Depends(get_db)) -> HTMLResponse:
    if not CODE.fullmatch(code):
        return _not_found(request)
    # Link previews (crawlers) are not someone opening the bag.
    view = await bag_service.load(db, code, count_open=not is_bot(request.headers.get("user-agent", "")))
    if view is None:
        return _not_found(request)
    # Stock and prices change: a short cache, then check again.
    return HTMLResponse(_render(request, view), headers={"Cache-Control": "public, max-age=60"})


# ---------- the preview card ----------

_cards: OrderedDict[str, tuple[float, bytes]] = OrderedDict()
CARD_TTL_SECONDS = 15 * 60
MAX_CARDS = 256


@router.get("/share/bag/{code}.png", include_in_schema=False)
async def saved_bag_card(code: str, db: AsyncSession = Depends(get_db)) -> Response:
    hit = _cards.get(code)
    if hit and time.monotonic() < hit[0]:
        png = hit[1]
    else:
        view = await bag_service.load(db, code, count_open=False) if CODE.fullmatch(code) else None
        if view is None:
            card = Card(places="A travel bag", kicker="TRAVEL BAG")
        else:
            n = len(view.items)
            # Catalog gadgets only: other names came from a browser and do
            # not go on a picture under our name.
            items = order_items([CardItem(i.name, i.priority or "recommended", image_key=i.image_key)
                                 for i in view.items if i.slug])
            await _load_thumbnails(items)
            # "Tk", not "৳": the card's font has no taka sign.
            chosen = f"Tk {view.chosen_total:,} of options chosen" if view.chosen_total else None
            card = Card(
                places=f"{n} gadget{'s' if n != 1 else ''} for the trip",
                kicker="TRAVEL BAG",
                dates=chosen,
                items=items, total=n,
            )
        png = await asyncio.to_thread(render, card)
        _cards[code] = (time.monotonic() + CARD_TTL_SECONDS, png)
        _cards.move_to_end(code)
        while len(_cards) > MAX_CARDS:
            _cards.popitem(last=False)
    return Response(png, media_type="image/png", headers={"Cache-Control": "public, max-age=900"})
