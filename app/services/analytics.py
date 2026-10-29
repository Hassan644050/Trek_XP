"""Anonymous, cookie-free visitor analytics.

What is counted, per day (in the home country's time zone):
- unique visitors and page views of the public pages (home, gadget index,
  gadget detail pages, compare pages), with the page, the external referrer and the
  device type;
- packing lists generated, by destination and trip type.

How it stays private:
- No cookies and nothing in the browser.
- IP addresses are never written anywhere. A visitor is a hash of that
  day's random salt + IP + browser string; the salt is deleted after the
  day ends, so old hashes cannot be tied back to anyone.
- Only daily totals are stored, never individual requests.
- Bots, link-preview fetchers, prefetches and signed-in staff are skipped.

How it stays cheap: requests only touch an in-memory buffer. A background
task writes the buffer to the database every few minutes in one short
transaction, so a visit never waits on (or wakes) the database, and up to
FLUSH_SECONDS of counts are lost if the process is killed hard.
"""

import asyncio
import hashlib
import logging
import os
import re
import secrets
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert

from app.auth.sessions import SESSION_COOKIE
from app.db.models import AnalyticsCount, AnalyticsSalt, AnalyticsVisitor


logger = logging.getLogger(__name__)

FLUSH_SECONDS = 300

# Bounds on the in-memory buffer between flushes. Labels partly come from
# request headers (referrer, browser), so without a cap a flood of made-up
# values could grow memory; past the cap new keys are dropped, existing
# ones still count.
MAX_BUFFERED_KEYS = 5_000
MAX_BUFFERED_VISITORS = 50_000
MAX_LABEL = 120

PAGE_VIEW = "page_view"
LIST = "list"
TRIP_TYPE = "trip_type"
REFERRER = "referrer"
DEVICE = "device"

_BOT = re.compile(
    r"bot|crawl|spider|slurp|curl|wget|python|httpx|aiohttp|java/|go-http|okhttp|"
    r"headless|lighthouse|pagespeed|preview|monitor|uptime|pingdom|facebookexternalhit|"
    r"whatsapp|telegram|slack|discord|embedly",
    re.IGNORECASE,
)


def _zone() -> ZoneInfo:
    return ZoneInfo(os.getenv("ANALYTICS_TIMEZONE", "Asia/Dhaka"))


def today() -> date:
    return datetime.now(_zone()).date()


def _clip(label: str) -> str:
    return " ".join(label.split())[:MAX_LABEL]


# ---------- classifying a request ----------


def page_label(path: str) -> str | None:
    """The public page a path is, or None for anything not counted."""
    if path in ("/", "/index.html"):
        return "home"
    if path == "/gadgets":
        return "gadgets"
    for prefix in ("/gadget/", "/compare/"):
        if path.startswith(prefix) and path.count("/") == 2 and len(path) > len(prefix):
            return path.removeprefix("/")
    return None


def is_bot(user_agent: str) -> bool:
    return not user_agent or bool(_BOT.search(user_agent))


def device_of(user_agent: str) -> str:
    if re.search(r"ipad|tablet", user_agent, re.IGNORECASE):
        return "tablet"
    if re.search(r"mobi|android|iphone", user_agent, re.IGNORECASE):
        return "mobile"
    return "desktop"


def external_referrer(referer: str | None, own_host: str | None) -> str | None:
    """The referring site's host, or None for internal or missing ones."""
    if not referer:
        return None
    host = (urlsplit(referer).hostname or "").lower().removeprefix("www.")
    own = (own_host or "").split(":")[0].lower().removeprefix("www.")
    if not host or host == own:
        return None
    return host


# ---------- the buffer ----------


@dataclass
class _Buffer:
    counts: Counter = field(default_factory=Counter)
    # (day, ip, user agent) -- hashed only at flush, so raw values live in
    # memory for minutes and are never written.
    visitors: set = field(default_factory=set)

    def __bool__(self) -> bool:
        return bool(self.counts or self.visitors)


_buffer = _Buffer()


def _count(day: date, event: str, label: str, n: int = 1) -> None:
    key = (day, event, _clip(label))
    if key in _buffer.counts or len(_buffer.counts) < MAX_BUFFERED_KEYS:
        _buffer.counts[key] += n


def record_page_view(request, status_code: int) -> None:
    """Count one public page view. Cheap and never raises: analytics must
    not be able to break a page."""
    try:
        # 304 is a repeat visit answered from the browser cache -- still a view.
        if request.method != "GET" or status_code not in (200, 304):
            return

        page = page_label(request.url.path)
        if page is None:
            return

        headers = request.headers
        user_agent = headers.get("user-agent", "")
        if is_bot(user_agent):
            return
        if headers.get("purpose") == "prefetch" or "prefetch" in headers.get("sec-purpose", ""):
            return
        # Coordinators and admins checking the site are not visitors.
        if SESSION_COOKIE in request.cookies:
            return

        day = today()
        _count(day, PAGE_VIEW, page)
        _count(day, DEVICE, device_of(user_agent))

        referrer = external_referrer(headers.get("referer"), headers.get("host"))
        if referrer:
            _count(day, REFERRER, referrer)

        ip = request.client.host if request.client else ""
        if len(_buffer.visitors) < MAX_BUFFERED_VISITORS:
            _buffer.visitors.add((day, ip, user_agent[:300]))
    except Exception:
        logger.warning("Could not record a page view", exc_info=True)


def record_list(destination: str, trip_types: str | list[str] | None) -> None:
    """Count one packing list generated, once for each of its trip types."""
    day = today()
    _count(day, LIST, destination or "unknown")
    for trip_type in [trip_types] if isinstance(trip_types, str) else (trip_types or []):
        _count(day, TRIP_TYPE, trip_type)


# ---------- writing to the database ----------


def visitor_hash(salt: str, ip: str, user_agent: str) -> str:
    return hashlib.sha256(f"{salt}|{ip}|{user_agent}".encode()).hexdigest()[:32]


async def _salt_for(db, day: date) -> str:
    salt = await db.scalar(select(AnalyticsSalt.salt).where(AnalyticsSalt.day == day))
    if salt:
        return salt

    # Two workers may race to create it; whichever row wins is the salt.
    await db.execute(
        insert(AnalyticsSalt)
        .values(day=day, salt=secrets.token_hex(32))
        .on_conflict_do_nothing(index_elements=["day"])
    )
    return await db.scalar(select(AnalyticsSalt.salt).where(AnalyticsSalt.day == day))


async def _write(db, pending: _Buffer) -> None:
    salts = {}
    for day in {v[0] for v in pending.visitors}:
        salts[day] = await _salt_for(db, day)

    if pending.visitors:
        await db.execute(
            insert(AnalyticsVisitor)
            .values([
                {"day": day, "visitor_hash": visitor_hash(salts[day], ip, ua)}
                for day, ip, ua in pending.visitors
            ])
            .on_conflict_do_nothing()
        )

    if pending.counts:
        stmt = insert(AnalyticsCount).values([
            {"day": day, "event": event, "label": label, "count": n}
            for (day, event, label), n in pending.counts.items()
        ])
        await db.execute(
            stmt.on_conflict_do_update(
                index_elements=["day", "event", "label"],
                set_={"count": AnalyticsCount.count + stmt.excluded.count},
            )
        )

    # Salts older than yesterday can no longer be needed -- deleting them is
    # what makes old visitor hashes anonymous.
    await db.execute(delete(AnalyticsSalt).where(AnalyticsSalt.day < today() - timedelta(days=1)))
    await db.commit()


def _restore(pending: _Buffer) -> None:
    for key, n in pending.counts.items():
        if key in _buffer.counts or len(_buffer.counts) < MAX_BUFFERED_KEYS:
            _buffer.counts[key] += n
    room = MAX_BUFFERED_VISITORS - len(_buffer.visitors)
    _buffer.visitors.update(list(pending.visitors)[:max(room, 0)])


async def flush_into(db) -> None:
    """Write the buffered counts using an open session, in one transaction.
    On failure they go back into the buffer for the next attempt."""
    global _buffer

    if not _buffer:
        return

    pending, _buffer = _buffer, _Buffer()

    try:
        await _write(db, pending)
    except Exception:
        await db.rollback()
        logger.warning("Analytics flush failed; keeping counts for the next try", exc_info=True)
        _restore(pending)


async def flush(sessionmaker) -> None:
    if not _buffer:
        return
    async with sessionmaker() as db:
        await flush_into(db)


async def flush_forever(sessionmaker_factory) -> None:
    """Background loop started with the app."""
    while True:
        await asyncio.sleep(FLUSH_SECONDS)
        try:
            await flush(sessionmaker_factory())
        except Exception:
            logger.warning("Analytics flush loop error", exc_info=True)


# ---------- reading it back ----------


async def summary(db, days: int) -> dict:
    end = today()
    start = end - timedelta(days=days - 1)

    visitors_by_day = dict(
        (
            await db.execute(
                select(AnalyticsVisitor.day, func.count())
                .where(AnalyticsVisitor.day >= start)
                .group_by(AnalyticsVisitor.day)
            )
        ).all()
    )

    rows = (
        await db.execute(
            select(AnalyticsCount.day, AnalyticsCount.event, func.sum(AnalyticsCount.count))
            .where(AnalyticsCount.day >= start, AnalyticsCount.event.in_([PAGE_VIEW, LIST]))
            .group_by(AnalyticsCount.day, AnalyticsCount.event)
        )
    ).all()
    per_day = {(d, e): int(n) for d, e, n in rows}

    daily = []
    for i in range(days):
        d = start + timedelta(days=i)
        daily.append({
            "day": d.isoformat(),
            "visitors": visitors_by_day.get(d, 0),
            "page_views": per_day.get((d, PAGE_VIEW), 0),
            "lists": per_day.get((d, LIST), 0),
        })

    async def top(event: str, limit: int = 10) -> list[dict]:
        total = func.sum(AnalyticsCount.count).label("n")
        result = await db.execute(
            select(AnalyticsCount.label, total)
            .where(AnalyticsCount.day >= start, AnalyticsCount.event == event)
            .group_by(AnalyticsCount.label)
            .order_by(total.desc(), AnalyticsCount.label)
            .limit(limit)
        )
        return [{"label": label, "count": int(n)} for label, n in result.all()]

    # Unique visitors over a window are distinct per day: the daily salt
    # deliberately makes the same person a new hash tomorrow.
    return {
        "days": days,
        "today": daily[-1],
        "totals": {
            "visitors": sum(r["visitors"] for r in daily),
            "page_views": sum(r["page_views"] for r in daily),
            "lists": sum(r["lists"] for r in daily),
        },
        "daily": daily,
        "top_pages": await top(PAGE_VIEW),
        "top_destinations": await top(LIST),
        "top_trip_types": await top(TRIP_TYPE),
        "top_referrers": await top(REFERRER),
        "devices": await top(DEVICE, 3),
    }
