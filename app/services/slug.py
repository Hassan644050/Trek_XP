"""URL slugs for gadget detail pages.

Hyphenated and apostrophe-stripped, matching the home page's own slug
scheme (see slugify() in index.html), so "Waterproof Dry Bag" becomes
"waterproof-dry-bag" and a destination link round-trips cleanly.
"""

import re

from sqlalchemy import func, select

from app.db.models import Gadget


SLUG_MAX = 120


def url_slug(text: str) -> str:
    cleaned = text.lower().replace("'", "").replace("’", "")
    cleaned = re.sub(r"[^a-z0-9]+", "-", cleaned).strip("-")

    return cleaned[:SLUG_MAX].strip("-")


async def unique_gadget_slug(db, name: str, *, except_id: int | None = None) -> str:
    """A slug for a gadget's name, with a numeric suffix if one is taken.

    Gadget names are unique case-insensitively, so a collision only happens
    when two names differ by punctuation ("Cafe" vs "Café"); the suffix
    keeps the URL unique anyway.
    """
    base = url_slug(name) or "gadget"
    candidate = base
    n = 1

    while True:
        query = select(Gadget.id).where(Gadget.slug == candidate)
        if except_id is not None:
            query = query.where(Gadget.id != except_id)

        if await db.scalar(query) is None:
            return candidate

        n += 1
        candidate = f"{base}-{n}"
