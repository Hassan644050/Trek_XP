"""In-process cache for the public, read-mostly lookups the home page makes.

Every home page view asked the database for the form options, the featured
destinations and the hero photos. Each lookup opens a fresh connection to
Neon (pooler + NullPool) -- measured at ~1.6s to connect and ~0.8s per query
from a developer machine -- so the page waited seconds for data that only
changes when an admin or coordinator edits the catalog.

So these reads are cached here:

- A value is served from memory for as long as it is cached. Once it is
  older than `refresh_after`, the next request still gets it instantly and
  a background task fetches a fresh copy (stale-while-revalidate), so no
  visitor waits on the database after the first.
- Only the first request for a key waits, and concurrent first requests
  share one database call.
- Every successful write under /api/admin or /api/coordinator clears all
  caches (see the middleware in main.py), so edits show up straight away.
  With several workers, the ones that did not handle the write catch up
  within `refresh_after`.
- A failed load is never cached: the caller falls back as it did before,
  and the next request tries the database again. A failed background
  refresh keeps serving the last good value.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Hashable
from typing import Any


logger = logging.getLogger(__name__)

_caches: list["ReadCache"] = []

# Strong references, so a background refresh is not garbage-collected
# mid-flight (asyncio only keeps weak references to tasks).
_background: set[asyncio.Task] = set()


class ReadCache:
    def __init__(self, name: str, *, refresh_after: float = 60.0, max_keys: int = 16):
        self.name = name
        self.refresh_after = refresh_after
        # Keys come from query parameters; a bound keeps made-up values from
        # growing memory without limit.
        self.max_keys = max_keys
        self._entries: dict[Hashable, tuple[float, Any]] = {}
        self._locks: dict[Hashable, asyncio.Lock] = {}
        self._refreshing: set[Hashable] = set()
        # Bumped by clear(): a load that started before a write must not
        # store what it read once the write has cleared the cache.
        self._generation = 0
        _caches.append(self)

    async def get(self, key: Hashable, load: Callable[[], Awaitable[Any]]) -> Any:
        entry = self._entries.get(key)

        if entry is not None:
            stored_at, value = entry
            if time.monotonic() - stored_at > self.refresh_after:
                self._refresh_in_background(key, load)
            return value

        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            # Another request may have filled it while this one waited.
            entry = self._entries.get(key)
            if entry is not None:
                return entry[1]

            generation = self._generation
            value = await load()
            self._store(key, value, generation)
            return value

    def clear(self) -> None:
        self._generation += 1
        self._entries.clear()

    def _refresh_in_background(self, key: Hashable, load) -> None:
        if key in self._refreshing:
            return
        self._refreshing.add(key)
        task = asyncio.create_task(self._refresh(key, load, self._generation))
        _background.add(task)
        task.add_done_callback(_background.discard)

    async def _refresh(self, key: Hashable, load, generation: int) -> None:
        try:
            self._store(key, await load(), generation)
        except Exception:
            logger.warning("Background refresh of %s cache failed; serving the last value",
                           self.name, exc_info=True)
        finally:
            self._refreshing.discard(key)

    def _store(self, key: Hashable, value: Any, generation: int) -> None:
        if generation != self._generation:
            return  # cleared by a write while this load was running

        if key not in self._entries and len(self._entries) >= self.max_keys:
            oldest = min(self._entries, key=lambda k: self._entries[k][0])
            del self._entries[oldest]

        self._entries[key] = (time.monotonic(), value)


def clear_read_caches() -> None:
    """Drop every cached public read -- called after catalog writes."""
    for cache in _caches:
        cache.clear()
