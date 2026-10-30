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


@dataclass
class Card:
    places: str                                  # "Cox's Bazar + Saint Martin's Island"
    dates: str | None = None                     # "28 Nov – 5 Dec · 8 days"
    trip: str | None = None                      # "Beach · Surfing"
    conditions: list[str] = field(default_factory=list)   # ["18–30°C", "Plug A/C/D/G/K · 220V"]
    items: list[CardItem] = field(default_factory=list)
    total: int = 0


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


def render(card: Card) -> bytes:
    img = Image.new("RGB", (WIDTH, HEIGHT), SURFACE)
    draw = ImageDraw.Draw(img)

    # ---- left: the trip ----
    draw.rectangle([0, 0, LEFT_W, HEIGHT], fill=GREEN_DEEP)
    inner = LEFT_W - 2 * PAD
    y = PAD
    draw.text((PAD, y), "TREK_XP", font=mono(22, 800), fill=AMBER)
    y += 64
    draw.text((PAD, y), "PACKING LIST FOR", font=mono(17, 600), fill=GREEN_SOFT)
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
    y += 44

    items = sorted(card.items, key=lambda i: _RANK.get(i.priority, 1))[:MAX_ROWS]
    if not items:
        message = "Gadgets for this trip, checked against the weather, plugs and voltage there."
        for line in _wrap(draw, message, sans(34, 800), x1 - x0, 4) or [message]:
            draw.text((x0, y + 20), line, font=sans(34, 800), fill=INK)
            y += 46

    row_h = 66
    for item in items:
        colour, wash = PRIORITY.get(item.priority, PRIORITY["recommended"])
        label = item.priority.upper()
        label_font = mono(14, 700)
        label_w = _width(draw, label, label_font) + 20
        mid = y + row_h // 2
        draw.rectangle([x0, mid - 8, x0 + 16, mid + 8], fill=colour)
        name_font = sans(30, 800)
        name = _ellipsize(draw, item.name, name_font, x1 - x0 - 34 - label_w - 16)
        draw.text((x0 + 34, mid), name, font=name_font, fill=INK, anchor="lm")
        draw.rectangle([x1 - label_w, mid - 14, x1, mid + 14], fill=wash)
        draw.text((x1 - label_w / 2, mid), label, font=label_font, fill=colour, anchor="mm")
        y += row_h
        draw.line([x0, y, x1, y], fill=LINE, width=2)

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
