"""The picture a shared packing list shows in WhatsApp, Facebook and
Messenger: a 1200x630 card with the trip and its top gadgets.

Chat apps show a link as its Open Graph image, so this card *is* what
friends see before they tap. Drawn with Pillow in the site's own fonts and
colours (Nunito and JetBrains Mono, the forest-green / amber tokens of
index.html), square corners like the rest of the design.

Pure: data in, PNG bytes out. Where the data comes from (the trip in the
link, the quick list) is the route's job -- see routes/home.py.
"""

import io
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


WIDTH, HEIGHT = 1200, 630
# Bump whenever the card's look changes. WhatsApp and Facebook remember a
# link's preview by its exact URL, so the version goes into the shared links
# and the image URL: new shares then get the new card, not a remembered one.
CARD_VERSION = 3
FONTS = Path(__file__).resolve().parents[1] / "static" / "fonts"

# The design tokens of index.html, converted from oklch.
GREEN_DEEP = "#0c2b19"
GREEN_MID = "#185b37"
GREEN_SOFT = "#bcd6c0"
AMBER = "#e4b750"
SURFACE = "#fcfaf1"
LINE = "#ccd4ca"
INK = "#131d17"
INK_SOFT = "#445c4c"
INK_FAINT = "#64776a"
PRIORITY = {  # marker / label colour, label background
    "essential": ("#095c34", "#ceefd3"),
    "recommended": ("#9a5505", "#feedc9"),
    "optional": ("#176490", "#d8f0fc"),
}
_RANK = {"essential": 0, "recommended": 1, "optional": 2}

MAX_ROWS = 6
LEFT_W = 460
PAD = 48


@dataclass
class CardItem:
    name: str
    priority: str = "recommended"
    image: bytes | None = None   # the gadget's thumbnail, when it has a photo
    image_key: str | None = None  # where to load it from (routes/home.py)


def order_items(items: list[CardItem]) -> list[CardItem]:
    """The rows the card shows: essentials first, and within a priority the
    ones with a photo, which make the card worth a look."""
    return sorted(items, key=lambda i: (_RANK.get(i.priority, 1), i.image_key is None and i.image is None))[:MAX_ROWS]


@dataclass
class Card:
    places: str                                  # "Cox's Bazar + Saint Martin's Island"
    dates: str | None = None                     # "28 Nov – 5 Dec · 8 days"
    trip: str | None = None                      # "Beach · Surfing"
    conditions: list[str] = field(default_factory=list)   # ["18–30°C", "Plug A/C/D/G/K · 220V"]
    items: list[CardItem] = field(default_factory=list)
    total: int = 0
    kicker: str = "PACKING LIST FOR"             # the small line above the title


@lru_cache(maxsize=32)
def _font(family: str, size: int, weight: int) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(FONTS / f"{family}.woff2"), size)
    try:
        font.set_variation_by_axes([weight])  # both are variable fonts
    except (OSError, AttributeError):
        pass
    return font


def sans(size: int, weight: int = 800) -> ImageFont.FreeTypeFont:
    return _font("Nunito", size, weight)


def mono(size: int, weight: int = 600) -> ImageFont.FreeTypeFont:
    return _font("JetBrainsMono", size, weight)


def _width(draw: ImageDraw.ImageDraw, text: str, font) -> float:
    return draw.textlength(text, font=font)


def _ellipsize(draw, text: str, font, max_width: float) -> str:
    if _width(draw, text, font) <= max_width:
        return text
    while text and _width(draw, text + "…", font) > max_width:
        text = text[:-1]
    return text.rstrip() + "…"


def _wrap(draw, text: str, font, max_width: float, max_lines: int) -> list[str] | None:
    """Word-wrapped lines, or None if it needs more than max_lines."""
    lines: list[str] = []
    for word in text.split():
        if lines and _width(draw, f"{lines[-1]} {word}", font) <= max_width:
            lines[-1] = f"{lines[-1]} {word}"
        else:
            lines.append(word)
    if len(lines) > max_lines or any(_width(draw, line, font) > max_width for line in lines):
        return None
    return lines


def _title(draw, text: str, max_width: float) -> tuple[list[str], ImageFont.FreeTypeFont]:
    """The biggest size at which the place names fit in three lines; failing
    that, three lines at the smallest size with the last one cut short."""
    for size in (64, 56, 48, 42, 36):
        font = sans(size, 900)
        lines = _wrap(draw, text, font, max_width, 3)
        if lines:
            return lines, font
    font = sans(36, 900)
    lines = _wrap(draw, text, font, max_width, 99) or [text]
    if len(lines) > 3:
        lines = lines[:2] + [_ellipsize(draw, " ".join(lines[2:]), font, max_width)]
    return [_ellipsize(draw, line, font, max_width) for line in lines], font


COLUMNS, GAP = 3, 18
TILE_H = 204       # a gadget's tile: picture, then its name
PICTURE_H = 150


def _tile(img: Image.Image, draw, item: CardItem, at: tuple[int, int], width: int) -> None:
    """One gadget: its photo on white, fitted whole (object-fit: contain, as
    on the site) -- or, without one, its initial on the priority's colour --
    with a priority stripe on top and the name underneath."""
    x, y = at
    colour, wash = PRIORITY.get(item.priority, PRIORITY["recommended"])
    photo = None
    if item.image:
        try:
            photo = Image.open(io.BytesIO(item.image)).convert("RGBA")
        except Exception:
            photo = None  # an unreadable file costs the picture, not the card

    box = [x, y, x + width - 1, y + PICTURE_H - 1]
    if photo is not None:
        draw.rectangle(box, fill="white", outline=LINE, width=2)
        photo.thumbnail((width - 24, PICTURE_H - 24), Image.LANCZOS)
        img.paste(photo, (x + (width - photo.width) // 2, y + (PICTURE_H - photo.height) // 2), photo)
    else:
        draw.rectangle(box, fill=wash)
        initial = (item.name.strip()[:1] or "?").upper()
        draw.text((x + width / 2, y + PICTURE_H / 2), initial, font=sans(72, 900), fill=colour, anchor="mm")
    draw.rectangle([x, y, x + width - 1, y + 5], fill=colour)

    name_font = sans(22, 800)
    lines = _wrap(draw, item.name, name_font, width, 2)
    if lines is None:
        first = _wrap(draw, item.name, name_font, width, 99) or [item.name]
        lines = [_ellipsize(draw, first[0], name_font, width)]
        if len(first) > 1:
            lines.append(_ellipsize(draw, " ".join(first[1:]), name_font, width))
    for n, line in enumerate(lines[:2]):
        draw.text((x, y + PICTURE_H + 10 + n * 26), line, font=name_font, fill=INK)


def render(card: Card) -> bytes:
    img = Image.new("RGB", (WIDTH, HEIGHT), SURFACE)
    draw = ImageDraw.Draw(img)

    # ---- left: the trip ----
    draw.rectangle([0, 0, LEFT_W, HEIGHT], fill=GREEN_DEEP)
    inner = LEFT_W - 2 * PAD
    y = PAD
    draw.text((PAD, y), "TREK_XP", font=mono(22, 800), fill=AMBER)
    y += 64
    draw.text((PAD, y), card.kicker, font=mono(17, 600), fill=GREEN_SOFT)
    y += 34
    lines, font = _title(draw, card.places, inner)
    for line in lines:
        draw.text((PAD, y), line, font=font, fill="white")
        y += int(font.size * 1.08)
    y += 14
    if card.dates:
        draw.text((PAD, y), _ellipsize(draw, card.dates, sans(26, 800), inner), font=sans(26, 800), fill="white")
        y += 40
    if card.trip:
        draw.text((PAD, y), _ellipsize(draw, card.trip, sans(24, 700), inner), font=sans(24, 700), fill=GREEN_SOFT)

    # Weather and power as chips along the bottom.
    chip_font = sans(22, 800)
    cy = HEIGHT - PAD
    for text in reversed(card.conditions[:2]):
        text = _ellipsize(draw, text, chip_font, inner - 32)
        cy -= 48
        draw.rectangle([PAD, cy, PAD + _width(draw, text, chip_font) + 32, cy + 40], fill=GREEN_MID)
        draw.text((PAD + 16, cy + 20), text, font=chip_font, fill="white", anchor="lm")
        cy -= 10

    # ---- right: the gadgets ----
    x0, x1 = LEFT_W + 56, WIDTH - 56
    y = PAD + 4
    draw.text((x0, y), "WHAT TO PACK", font=mono(18, 700), fill=INK_FAINT)
    if card.total:
        count = f"{card.total} ITEM{'S' if card.total != 1 else ''}"
        draw.text((x1, y), count, font=mono(18, 700), fill=INK_FAINT, anchor="ra")
    y += 40

    items = order_items(card.items)
    if not items:
        message = "Gadgets for this trip, checked against the weather, plugs and voltage there."
        for line in _wrap(draw, message, sans(34, 800), x1 - x0, 4) or [message]:
            draw.text((x0, y + 20), line, font=sans(34, 800), fill=INK)
            y += 46

    # Three across, two down. Chat apps show this card at a quarter of its
    # size on a phone, so big pictures carry it; the names are for the
    # larger Facebook view.
    tile_w = (x1 - x0 - (COLUMNS - 1) * GAP) // COLUMNS
    for i, item in enumerate(items):
        col, row = i % COLUMNS, i // COLUMNS
        tx, ty = x0 + col * (tile_w + GAP), y + row * (TILE_H + GAP)
        _tile(img, draw, item, (tx, ty), tile_w)

    # ---- footer: the invitation to tap ----
    fy = HEIGHT - PAD - 10
    more = card.total - len(items)
    if more > 0:
        draw.text((x0, fy), f"+{more} more", font=sans(24, 800), fill=INK_SOFT, anchor="ls")
    # The arrow is drawn: Nunito has no "→".
    green = PRIORITY["essential"][0]
    ay = fy - 10
    draw.line([x1 - 22, ay, x1, ay], fill=green, width=4)
    draw.polygon([(x1 + 2, ay), (x1 - 9, ay - 9), (x1 - 9, ay + 9)], fill=green)
    draw.text((x1 - 34, fy), "Open the full list", font=sans(26, 900), fill=green, anchor="rs")

    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()
