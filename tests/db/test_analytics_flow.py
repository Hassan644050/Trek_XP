"""Visitor analytics against a real database: flush, dedupe, salts, summary."""

from datetime import timedelta

from app.db.models import AnalyticsSalt
from app.services import analytics
from tests.db.conftest import run
from tests.test_analytics import DESKTOP, PHONE, request


def test_flush_and_summary_through_the_admin_endpoint(admin):
    analytics.record_page_view(request("/", ua=PHONE, referer="https://facebook.com/x"), 200)
    analytics.record_page_view(request("/gadgets", ua=PHONE), 200)
    analytics.record_page_view(request("/", ua=DESKTOP, ip="198.51.100.2"), 200)
    analytics.record_list("Jaflong", "hiking")

    body = admin.get("/api/admin/analytics?days=7").json()

    assert body["today"] == {"day": analytics.today().isoformat(), "visitors": 2, "page_views": 3, "lists": 1}
    assert body["top_destinations"] == [{"label": "Jaflong", "count": 1}]
    assert body["top_referrers"] == [{"label": "facebook.com", "count": 1}]
    assert len(body["daily"]) == 7
    assert not analytics._buffer  # flushed by the request


def test_counts_accumulate_and_visitors_dedupe_across_flushes(admin):
    for _ in range(2):
        analytics.record_page_view(request("/"), 200)
        body = admin.get("/api/admin/analytics?days=7").json()

    assert body["today"]["page_views"] == 2
    assert body["today"]["visitors"] == 1


def test_old_salts_are_deleted(admin):
    async def plant(session):
        session.add(AnalyticsSalt(day=analytics.today() - timedelta(days=3), salt="old"))
        await session.commit()

    run(plant)
    analytics.record_page_view(request("/"), 200)
    admin.get("/api/admin/analytics?days=7")

    async def salts(session):
        from sqlalchemy import select
        return list((await session.scalars(select(AnalyticsSalt.day))).all())

    assert run(salts) == [analytics.today()]


def test_coordinators_cannot_read_analytics(coordinator):
    assert coordinator.get("/api/admin/analytics").status_code == 403
