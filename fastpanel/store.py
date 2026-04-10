"""
fastpanel.store
~~~~~~~~~~~~~~~

Thread-safe, LRU-evicting in-memory store for per-request panel data.

Each request processed by FastPanel is assigned a UUID4 ``request_id``.
Panel data collected during that request is stored here under that ID
and later fetched by the toolbar UI via the internal API.

The store is intentionally simple — a dict with an ``OrderedDict``-based
LRU eviction policy. We don't use ``functools.lru_cache`` (which is
function-scoped) or an external cache (which would be a dep). The goal
is correct, predictable behavior in a single-process dev server.

Concurrency model: FastAPI with uvicorn runs in a single process by
default (dev mode). However, it *is* async — multiple requests can be
in-flight concurrently via the asyncio event loop. The store uses an
``asyncio.Lock`` to protect mutations. Reads don't lock because dict
``__getitem__`` is atomic in CPython and we only care about logical
consistency, not byte-level atomicity.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from typing import Any


class RequestStore:
    """LRU-evicting in-memory store for per-request panel data.

    The store is keyed by ``request_id`` (a UUID4 string). When the number
    of stored requests exceeds ``max_requests``, the oldest entry is evicted
    to bound memory usage.

    This class is designed to be instantiated once per ``FastPanel`` instance
    and shared across all requests.

    Args:
        max_requests: Maximum number of requests to keep. Defaults to 100.

    Example::

        store = RequestStore(max_requests=50)
        store.set("abc-123", {"sql": {...}, "request": {...}})
        data = store.get("abc-123")
    """

    def __init__(self, max_requests: int = 100) -> None:
        self._max_requests = max_requests
        # OrderedDict preserves insertion order, giving us O(1) LRU eviction:
        # move_to_end() on access, popitem(last=False) to evict the oldest.
        self._data: OrderedDict[str, dict[str, Any]] = OrderedDict()
        # asyncio.Lock is the right primitive here — we're in an async context
        # and we need to serialise writes, not reads.
        self._lock = asyncio.Lock()

    async def set(self, request_id: str, data: dict[str, Any]) -> None:
        """Store panel data for a request.

        If storing this entry would exceed ``max_requests``, the oldest
        entry is evicted first (LRU policy).

        Args:
            request_id: UUID4 string identifying the request.
            data: Panel data dict to store.
        """
        async with self._lock:
            if request_id in self._data:
                # Update in place and move to end (most recently used).
                self._data[request_id] = data
                self._data.move_to_end(request_id)
            else:
                if len(self._data) >= self._max_requests:
                    # Evict the oldest entry (the first item in the OrderedDict).
                    self._data.popitem(last=False)
                self._data[request_id] = data

    def get(self, request_id: str) -> dict[str, Any] | None:
        """Retrieve panel data for a request.

        Returns ``None`` if the request ID is not found (either never stored,
        or already evicted).

        Note: This is intentionally synchronous. In CPython, dict ``__getitem__``
        is atomic at the GIL level, and we never need to await a read. Callers
        in async routes can call this without ``await``.

        Args:
            request_id: UUID4 string identifying the request.

        Returns:
            The stored panel data dict, or ``None`` if not found.
        """
        return self._data.get(request_id)

    async def delete(self, request_id: str) -> None:
        """Remove panel data for a specific request.

        No-op if the request ID is not in the store.

        Args:
            request_id: UUID4 string identifying the request.
        """
        async with self._lock:
            self._data.pop(request_id, None)

    async def clear(self) -> None:
        """Remove all stored request data.

        Primarily useful in tests to reset state between test cases.
        """
        async with self._lock:
            self._data.clear()

    def __len__(self) -> int:
        """Return the number of requests currently in the store."""
        return len(self._data)

    def __contains__(self, request_id: str) -> bool:
        """Support ``request_id in store`` membership test."""
        return request_id in self._data

    def list(self) -> list[dict[str, Any]]:
        """Return summaries of all stored requests, newest first.

        Each summary contains the fields needed to render the request list
        in the standalone debugger UI without loading full panel data.

        Returns:
            List of summary dicts, most recent request first.
        """
        summaries = []
        for request_id, data in reversed(list(self._data.items())):
            panels = data.get("panels", {})
            req = panels.get("request", {})
            resp = panels.get("response", {})
            perf = panels.get("performance", {})
            sql = panels.get("sql", {})
            summaries.append({
                "request_id": request_id,
                "method": req.get("method", "?"),
                "path": req.get("path", "/"),
                "status_code": resp.get("status_code", 0),
                "total_ms": round(perf.get("total_ms", 0.0), 1),
                "sql_count": sql.get("total_queries", 0) if sql else 0,
            })
        return summaries

    @property
    def max_requests(self) -> int:
        """The configured maximum number of requests."""
        return self._max_requests
