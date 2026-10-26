"""How buying-option stock is worded and shown."""

from datetime import datetime, timedelta, timezone

import pytest

from app.services.gadgets.stock import can_buy, stock_status, updated_ago


@pytest.mark.parametrize("qty,status,label", [
    (None, "out", "Out of stock"),        # a missing count is never "available"
    (0, "out", "Out of stock"),
    (1, "low", "Only 1 left"),
    (3, "low", "Only 3 left"),
    (4, "in", "In stock"),
    (250, "in", "In stock"),
])
def test_stock_status(qty, status, label):
    assert stock_status(qty) == (status, label)


def test_only_a_positive_count_can_be_bought():
    assert can_buy(1) and not can_buy(0) and not can_buy(None)


def test_updated_ago():
    now = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)
    assert updated_ago(None, now) is None
    assert updated_ago(now - timedelta(hours=3), now) == "updated today"
    assert updated_ago(now - timedelta(days=1), now) == "updated yesterday"
    assert updated_ago(now - timedelta(days=9), now) == "updated 9 days ago"
    assert updated_ago(now - timedelta(days=120), now) == "updated Jun 2026"
