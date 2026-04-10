"""
fastpanel.panels.cache
~~~~~~~~~~~~~~~~~~~~~~~

Cache panel — tracks cache get/set/delete/miss events during the request.

Unlike the SQL panel (which hooks into SQLAlchemy's event system), the
cache panel cannot hook into arbitrary cache libraries automatically.
Instead, it exposes a ``CacheTracker`` proxy object that wraps a
cache backend (Redis client or in-memory dict) and records operations.

Usage in application code::

    from fastpanel import FastPanel
    from fastpanel.panels.cache import CacheTracker

    # Wrap your cache client at startup
    raw_redis = redis.asyncio.Redis.from_url("redis://localhost")
    cache = CacheTracker(raw_redis)

    # Use cache normally — operations are tracked automatically
    await cache.get("my_key")
    await cache.set("my_key", "value")

The ``CacheTracker`` is a lightweight async proxy — it delegates all
operations to the underlying client and records events into the
request-scoped buffer via the same ``ContextVar`` pattern used by
the SQL and Logging panels.

For convenience, ``CachePanel`` also exposes a simple ``InMemoryCache``
that stores values in a dict, useful for testing and simple use cases
that don't require Redis.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from starlette.requests import Request
from starlette.responses import Response

from fastpanel.panels.base import AbstractPanel

# Per-request cache event buffer.
_request_cache_buffer: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "fastpanel_cache_buffer", default=None
)


class InMemoryCache:
    """Simple async-compatible in-memory cache backed by a dict.

    Suitable for development and testing. Not thread-safe (fine for asyncio).

    Example::

        cache = CacheTracker(InMemoryCache())
        await cache.set("key", "value", ttl=60)
        value = await cache.get("key")
    """

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}

    async def get(self, key: str) -> Any:
        """Return the value for *key*, or ``None`` if not set."""
        return self._store.get(key)

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Store *value* under *key*. *ttl* is accepted but ignored."""
        self._store[key] = value

    async def delete(self, key: str) -> None:
        """Remove *key* from the cache. No-op if not present."""
        self._store.pop(key, None)

    async def clear(self) -> None:
        """Remove all entries."""
        self._store.clear()


class CacheTracker:
    """Async proxy that wraps a cache client and records operations.

    Pass any cache backend — a Redis ``redis.asyncio.Redis`` client,
    an ``InMemoryCache`` instance, or any object with async ``get``,
    ``set``, and ``delete`` methods.

    All operations are forwarded to the underlying client. If a
    request context is active (``_request_cache_buffer`` is set), the
    operation is also recorded in the per-request buffer.

    Args:
        backend: The underlying cache client to delegate to.

    Example::

        import redis.asyncio
        raw = redis.asyncio.Redis.from_url("redis://localhost")
        cache = CacheTracker(raw)
        await cache.set("user:1", '{"name": "Alice"}')
    """

    def __init__(self, backend: Any) -> None:
        self._backend = backend

    def _record(self, operation: str, key: str, hit: bool | None = None) -> None:
        """Append a cache event to the request buffer if one is active.

        Args:
            operation: One of ``"get"``, ``"set"``, ``"delete"``, ``"miss"``.
            key: The cache key involved in the operation.
            hit: For ``"get"`` operations, whether the key existed.
        """
        buffer = _request_cache_buffer.get()
        if buffer is not None:
            buffer.append({"operation": operation, "key": key, "hit": hit})

    async def get(self, key: str) -> Any:
        """Get a value from the cache, recording a hit or miss.

        Args:
            key: Cache key to retrieve.

        Returns:
            Cached value, or ``None`` if not found.
        """
        value = await self._backend.get(key)
        # Record as "get" with hit=True/False rather than separate "miss"
        # events — this is cleaner to aggregate in get_data().
        self._record("get", key, hit=value is not None)
        return value

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Set a value in the cache.

        Args:
            key: Cache key.
            value: Value to store.
            ttl: Time-to-live in seconds. Passed through to the backend if
                the backend accepts it. ``InMemoryCache`` ignores it.
        """
        # Pass ttl only if the backend accepts it — duck-typing approach.
        try:
            await self._backend.set(key, value, ttl)
        except TypeError:
            await self._backend.set(key, value)
        self._record("set", key)

    async def delete(self, key: str) -> None:
        """Delete a value from the cache.

        Args:
            key: Cache key to remove.
        """
        await self._backend.delete(key)
        self._record("delete", key)

    @property
    def backend(self) -> Any:
        """The underlying cache backend."""
        return self._backend


class CachePanel(AbstractPanel):
    """Tracks cache get/set/delete events during the request.

    Unlike the SQL panel, this panel does not automatically instrument
    cache clients. The application must use ``CacheTracker`` to wrap
    its cache backend for events to be captured.

    Stored data schema::

        {
            "events": [
                {"operation": "get", "key": "user:1", "hit": true},
                {"operation": "set", "key": "user:1", "hit": null},
                ...
            ],
            "total_events": 5,
            "hits": 3,
            "misses": 1,
            "sets": 1,
            "deletes": 0,
            "hit_rate": 75.0
        }
    """

    panel_id = "cache"
    title = "Cache"
    template_name = "cache.html"

    def __init__(self) -> None:
        super().__init__()
        self._events: list[dict[str, Any]] = []
        self._buffer_token: Any = None

    def reset(self) -> None:
        """Clear captured cache events for a new request."""
        self._events = []

    async def process_request(self, request: Request) -> None:
        """Open the request cache event buffer.

        Args:
            request: The incoming Starlette ``Request`` object.
        """
        self._events = []
        self._buffer_token = _request_cache_buffer.set(self._events)

    async def process_response(self, request: Request, response: Response) -> None:
        """Close the request cache event buffer.

        Args:
            request: The incoming Starlette ``Request`` object.
            response: The outgoing Starlette ``Response`` object.
        """
        if self._buffer_token is not None:
            _request_cache_buffer.reset(self._buffer_token)
            self._buffer_token = None

    def get_stats(self) -> str:
        """Return the cache hit rate as badge text (e.g. ``"75%"``)."""
        gets = [e for e in self._events if e["operation"] == "get"]
        if not gets:
            return "—"
        hits = sum(1 for e in gets if e["hit"])
        rate = (hits / len(gets)) * 100
        return f"{rate:.0f}%"

    def get_data(self) -> dict[str, Any]:
        """Return the full cache event log."""
        gets = [e for e in self._events if e["operation"] == "get"]
        hits = sum(1 for e in gets if e["hit"])
        misses = len(gets) - hits
        sets = sum(1 for e in self._events if e["operation"] == "set")
        deletes = sum(1 for e in self._events if e["operation"] == "delete")

        hit_rate = (hits / len(gets) * 100) if gets else 0.0

        return {
            "events": list(self._events),
            "total_events": len(self._events),
            "hits": hits,
            "misses": misses,
            "sets": sets,
            "deletes": deletes,
            "hit_rate": round(hit_rate, 1),
        }
