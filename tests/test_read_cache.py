"""The in-process cache for public reads: hits, background refresh,
invalidation after writes, and failures that must not be cached."""

import asyncio
from types import SimpleNamespace

import pytest

from app.services import read_cache
from app.services.read_cache import ReadCache


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(read_cache.time, "monotonic", c)
    return c


def counting_loader(values):
    calls = []

    async def load():
        calls.append(1)
        return values[min(len(calls), len(values)) - 1]

    return load, calls


def test_a_hit_does_not_reload():
    async def scenario():
        cache = ReadCache("t")
        load, calls = counting_loader(["a"])
        assert await cache.get("k", load) == "a"
        assert await cache.get("k", load) == "a"
        return calls

    assert len(asyncio.run(scenario())) == 1


def test_concurrent_first_requests_share_one_load():
    async def scenario():
        cache = ReadCache("t")
        calls = []

        async def slow():
            calls.append(1)
            await asyncio.sleep(0.01)
            return "a"

        results = await asyncio.gather(*(cache.get("k", slow) for _ in range(5)))
        return results, calls

    results, calls = asyncio.run(scenario())
    assert results == ["a"] * 5 and len(calls) == 1


def test_a_stale_value_is_served_while_it_refreshes(clock):
    async def scenario():
        cache = ReadCache("t", refresh_after=60)
        load, _ = counting_loader(["old", "new"])
        await cache.get("k", load)

        clock.now += 61
        served = await cache.get("k", load)    # instant, still the old value
        await asyncio.sleep(0)                 # let the refresh run
        await asyncio.sleep(0)
        return served, await cache.get("k", load)

    assert asyncio.run(scenario()) == ("old", "new")


def test_a_failed_load_is_not_cached():
    async def scenario():
        cache = ReadCache("t")

        async def broken():
            raise RuntimeError("db down")

        with pytest.raises(RuntimeError):
            await cache.get("k", broken)

        load, calls = counting_loader(["a"])
        return await cache.get("k", load), calls

    value, calls = asyncio.run(scenario())
    assert value == "a" and len(calls) == 1


def test_clear_drops_values_and_discards_loads_that_started_before_it():
    async def scenario():
        cache = ReadCache("t")
        gate = asyncio.Event()

        async def slow_old():
            await gate.wait()
            return "read before the write"

        pending = asyncio.create_task(cache.get("k", slow_old))
        await asyncio.sleep(0)
        cache.clear()             # a write lands while the load is in flight
        gate.set()
        await pending

        load, _ = counting_loader(["fresh"])
        return await cache.get("k", load)

    assert asyncio.run(scenario()) == "fresh"


def test_keys_are_bounded(clock):
    async def scenario():
        cache = ReadCache("t", max_keys=2)
        for key in ("a", "b", "c"):
            clock.now += 1

            async def load(key=key):
                return key

            await cache.get(key, load)
        return set(cache._entries)

    assert asyncio.run(scenario()) == {"b", "c"}  # the oldest was evicted


@pytest.mark.parametrize("method,path,status,clears", [
    ("POST", "/api/coordinator/gadgets", 201, True),
    ("PUT", "/api/admin/heroes", 200, True),
    ("DELETE", "/api/admin/divisions/3", 204, True),
    ("POST", "/api/coordinator/gadgets", 403, False),   # refused: nothing changed
    ("GET", "/api/admin/heroes", 200, False),           # reads never clear
    ("POST", "/recommend", 200, False),                 # not a catalog write
    ("POST", "/api/auth/login", 200, False),
])
def test_only_successful_catalog_writes_clear_the_caches(monkeypatch, method, path, status, clears):
    from app.main import drop_read_caches_after_catalog_writes as middleware

    cleared = []
    monkeypatch.setattr("app.main.clear_read_caches", lambda: cleared.append(1))

    async def call_next(request):
        return SimpleNamespace(status_code=status)

    request = SimpleNamespace(method=method, url=SimpleNamespace(path=path))
    asyncio.run(middleware(request, call_next))

    assert bool(cleared) is clears


@pytest.mark.parametrize("path,expected", [
    ("/", "no-cache"), ("/bag.js", "no-cache"), ("/site-header.css", "no-cache"),
    ("/coordinator", "no-cache"), ("/health", None),
])
def test_pages_scripts_and_styles_are_revalidated(path, expected):
    from fastapi.testclient import TestClient

    from app.main import app

    assert TestClient(app).get(path).headers.get("cache-control") == expected
