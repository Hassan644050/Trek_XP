"""How a buying option's stock is described to travellers.

stock_quantity is kept by coordinators per buying option and is required:
nothing is shown as available without a confirmed count. Options added
before it was required were set to 0 until a coordinator enters theirs.
"""

from datetime import datetime, timezone

# At or below this many units, say how many are left.
LOW_STOCK = 3

IN, LOW, OUT = "in", "low", "out"


def stock_status(quantity: int | None) -> tuple[str, str]:
    """(status key, label) -- the key drives styling and filtering. A
    missing count is treated as none on hand, never as available."""
    if not quantity or quantity <= 0:
        return OUT, "Out of stock"
    if quantity <= LOW_STOCK:
        return LOW, f"Only {quantity} left"
    return IN, "In stock"


def can_buy(quantity: int | None) -> bool:
    return bool(quantity) and quantity > 0


def updated_ago(when: datetime | None, now: datetime | None = None) -> str | None:
    """'updated today' / 'updated 3 days ago' -- how fresh the count is."""
    if when is None:
        return None
    now = now or datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    days = (now - when).days
    if days <= 0:
        return "updated today"
    if days == 1:
        return "updated yesterday"
    if days < 60:
        return f"updated {days} days ago"
    return f"updated {when:%b %Y}"
