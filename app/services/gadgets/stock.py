"""How a buying option's stock is described to travellers.

stock_quantity is kept by coordinators per buying option; None means it is
not tracked (a seller's listing whose stock we do not hold).
"""

from datetime import datetime, timezone

# At or below this many units, say how many are left.
LOW_STOCK = 3

IN, LOW, OUT, UNKNOWN = "in", "low", "out", "unknown"


def stock_status(quantity: int | None) -> tuple[str, str]:
    """(status key, label) -- the key drives styling and filtering."""
    if quantity is None:
        return UNKNOWN, "Check with seller"
    if quantity <= 0:
        return OUT, "Out of stock"
    if quantity <= LOW_STOCK:
        return LOW, f"Only {quantity} left"
    return IN, "In stock"


def can_buy(quantity: int | None) -> bool:
    """Out of stock is the only state that rules a buying option out."""
    return quantity is None or quantity > 0


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
