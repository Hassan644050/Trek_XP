"""Anonymous visitor counting: what is counted, what is skipped, and the
bounds on the in-memory buffer."""

from types import SimpleNamespace

import pytest

from app.services import analytics
from app.services.analytics import (
    DEVICE, LIST, PAGE_VIEW, REFERRER, TRIP_TYPE,
    device_of, external_referrer, is_bot, page_label, record_list, record_page_view, visitor_hash,
)

PHONE = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/130 Mobile Safari/537.36"
DESKTOP = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130 Safari/537.36"


def request(path="/", ua=DESKTOP, method="GET", referer=None, cookies=None, ip="203.0.113.7", **headers):
    hdrs = {"user-agent": ua, "host": "trekxp.example", **headers}
    if referer:
        hdrs["referer"] = referer
    return SimpleNamespace(
        method=method, url=SimpleNamespace(path=path), headers=hdrs,
        cookies=cookies or {}, client=SimpleNamespace(host=ip),
    )


def counts():
    return {(event, label): n for (_, event, label), n in analytics._buffer.counts.items()}


@pytest.mark.parametrize("path,label", [
    ("/", "home"), ("/index.html", "home"), ("/gadgets", "gadgets"),
    ("/gadget/power-bank", "gadget/power-bank"),
    ("/compare/power-bank", "compare/power-bank"),
    ("/gadget/", None), ("/gadget/a/b", None), ("/coordinator", None),
    ("/api/auth/me", None), ("/site-header.css", None), ("/media/x.webp", None),
])
def test_page_label(path, label):
    assert page_label(path) == label


@pytest.mark.parametrize("ua,bot", [
    (DESKTOP, False), (PHONE, False), ("", True), ("curl/8.5", True),
    ("Mozilla/5.0 (compatible; Googlebot/2.1)", True), ("facebookexternalhit/1.1", True),
    ("WhatsApp/2.23", True), ("python-httpx/0.28", True),
])
def test_is_bot(ua, bot):
    assert is_bot(ua) is bot


def test_device_of():
    assert device_of(PHONE) == "mobile"
    assert device_of(DESKTOP) == "desktop"
    assert device_of("Mozilla/5.0 (iPad; CPU OS 17_0)") == "tablet"


def test_external_referrer_ignores_own_site_and_strips_www():
    assert external_referrer("https://www.facebook.com/post/1", "trekxp.example") == "facebook.com"
    assert external_referrer("https://trekxp.example/gadgets", "trekxp.example:443") is None
    assert external_referrer(None, "trekxp.example") is None
    assert external_referrer("not a url", "trekxp.example") is None


def test_a_page_view_counts_page_device_referrer_and_visitor():
    record_page_view(request("/", ua=PHONE, referer="https://m.facebook.com/x"), 200)

    assert counts() == {(PAGE_VIEW, "home"): 1, (DEVICE, "mobile"): 1, (REFERRER, "m.facebook.com"): 1}
    assert len(analytics._buffer.visitors) == 1


def test_a_cached_repeat_visit_still_counts():
    record_page_view(request("/"), 304)
    assert counts()[(PAGE_VIEW, "home")] == 1


@pytest.mark.parametrize("req,status", [
    (request("/", ua="curl/8.5"), 200),                         # bot
    (request("/", cookies={"trekxp_session": "x"}), 200),       # signed-in staff
    (request("/", method="HEAD"), 200),
    (request("/gadget/nope"), 404),
    (request("/coordinator"), 200),                             # not a public page
    (request("/", purpose="prefetch"), 200),
    (request("/", **{"sec-purpose": "prefetch;prerender"}), 200),
])
def test_skipped_requests(req, status):
    record_page_view(req, status)
    assert not analytics._buffer


def test_the_same_visitor_is_one_entry_per_day():
    for path in ("/", "/gadgets", "/gadget/dry-bag"):
        record_page_view(request(path), 200)

    assert len(analytics._buffer.visitors) == 1
    assert sum(n for (e, _), n in counts().items() if e == PAGE_VIEW) == 3


def test_record_list_counts_destination_and_trip_type():
    record_list("Cox's Bazar", "beach")
    record_list("Cox's Bazar", "beach")

    assert counts() == {(LIST, "Cox's Bazar"): 2, (TRIP_TYPE, "beach"): 2}


def test_labels_are_clipped_and_new_keys_are_capped(monkeypatch):
    monkeypatch.setattr(analytics, "MAX_BUFFERED_KEYS", 3)
    record_list("x" * 500, None)
    assert len(next(iter(counts()))[1]) == analytics.MAX_LABEL

    for i in range(10):
        record_list(f"place {i}", None)
    assert len(analytics._buffer.counts) == 3


def test_recording_never_raises():
    record_page_view(SimpleNamespace(method="GET"), 200)  # malformed request object
    assert not analytics._buffer


def test_visitor_hash_depends_on_the_salt():
    a = visitor_hash("salt-1", "203.0.113.7", DESKTOP)
    assert a == visitor_hash("salt-1", "203.0.113.7", DESKTOP)
    assert a != visitor_hash("salt-2", "203.0.113.7", DESKTOP)  # tomorrow: a new, unlinkable hash
    assert "203.0.113.7" not in a


def test_the_middleware_counts_a_real_home_page_request(client):
    client.get("/", headers={"user-agent": DESKTOP})
    client.get("/health", headers={"user-agent": DESKTOP})

    assert counts().get((PAGE_VIEW, "home")) == 1
    assert not any(label == "health" for _, label in counts())
