"""Tests for the CachePanel, CacheTracker, and InMemoryCache."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from fastpanel.panels.cache import CachePanel, CacheTracker, InMemoryCache


@pytest.fixture
def cache_panel() -> CachePanel:
    panel = CachePanel()
    panel.enable(MagicMock())
    return panel


@pytest.fixture
def in_memory_cache() -> InMemoryCache:
    return InMemoryCache()


@pytest.fixture
def tracker(in_memory_cache: InMemoryCache) -> CacheTracker:
    return CacheTracker(in_memory_cache)


# ─── InMemoryCache tests ──────────────────────────────────────────────────────

async def test_in_memory_cache_set_and_get(in_memory_cache: InMemoryCache):
    await in_memory_cache.set("key", "value")
    assert await in_memory_cache.get("key") == "value"


async def test_in_memory_cache_miss_returns_none(in_memory_cache: InMemoryCache):
    assert await in_memory_cache.get("nonexistent") is None


async def test_in_memory_cache_delete(in_memory_cache: InMemoryCache):
    await in_memory_cache.set("key", "value")
    await in_memory_cache.delete("key")
    assert await in_memory_cache.get("key") is None


async def test_in_memory_cache_clear(in_memory_cache: InMemoryCache):
    await in_memory_cache.set("a", 1)
    await in_memory_cache.set("b", 2)
    await in_memory_cache.clear()
    assert await in_memory_cache.get("a") is None


# ─── CacheTracker tests ───────────────────────────────────────────────────────

async def test_tracker_get_hit_recorded(cache_panel, tracker):
    req, resp = MagicMock(), MagicMock()
    await cache_panel.process_request(req)
    await tracker.backend.set("mykey", "value")  # set directly on backend
    await tracker.get("mykey")
    await cache_panel.process_response(req, resp)
    data = cache_panel.get_data()
    assert data["hits"] == 1
    assert data["misses"] == 0


async def test_tracker_get_miss_recorded(cache_panel, tracker):
    req, resp = MagicMock(), MagicMock()
    await cache_panel.process_request(req)
    await tracker.get("absent_key")
    await cache_panel.process_response(req, resp)
    data = cache_panel.get_data()
    assert data["hits"] == 0
    assert data["misses"] == 1


async def test_tracker_set_recorded(cache_panel, tracker):
    req, resp = MagicMock(), MagicMock()
    await cache_panel.process_request(req)
    await tracker.set("key", "val")
    await cache_panel.process_response(req, resp)
    data = cache_panel.get_data()
    assert data["sets"] == 1


async def test_tracker_delete_recorded(cache_panel, tracker):
    req, resp = MagicMock(), MagicMock()
    await cache_panel.process_request(req)
    await tracker.delete("key")
    await cache_panel.process_response(req, resp)
    data = cache_panel.get_data()
    assert data["deletes"] == 1


async def test_hit_rate_calculation(cache_panel, tracker):
    req, resp = MagicMock(), MagicMock()
    await cache_panel.process_request(req)
    await tracker.set("k1", "v1")
    await tracker.set("k2", "v2")
    # 3 gets: 2 hits, 1 miss → 66.7%
    await tracker.get("k1")  # hit
    await tracker.get("k2")  # hit
    await tracker.get("k3")  # miss
    await cache_panel.process_response(req, resp)
    data = cache_panel.get_data()
    assert data["hits"] == 2
    assert data["misses"] == 1
    assert abs(data["hit_rate"] - 66.7) < 1.0


async def test_no_events_hit_rate_dash(cache_panel):
    assert cache_panel.get_stats() == "—"


async def test_get_stats_with_hits(cache_panel, tracker):
    req, resp = MagicMock(), MagicMock()
    await cache_panel.process_request(req)
    await tracker.set("k", "v")
    await tracker.get("k")  # hit → 100%
    await cache_panel.process_response(req, resp)
    assert cache_panel.get_stats() == "100%"


async def test_reset_clears_events(cache_panel, tracker):
    req, resp = MagicMock(), MagicMock()
    await cache_panel.process_request(req)
    await tracker.get("k")
    await cache_panel.process_response(req, resp)
    assert cache_panel.get_data()["total_events"] == 1
    cache_panel.reset()
    assert cache_panel.get_data()["total_events"] == 0


async def test_events_outside_request_context_not_captured(tracker):
    """CacheTracker operations outside a request context are not recorded."""
    panel = CachePanel()
    await tracker.get("some_key")
    # No process_request called, so nothing in the panel
    assert panel.get_data()["total_events"] == 0


async def test_panel_id_and_title():
    assert CachePanel.panel_id == "cache"
    assert CachePanel.title == "Cache"
