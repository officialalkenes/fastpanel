"""Tests for fastpanel.store.RequestStore."""

from __future__ import annotations

from fastpanel.store import RequestStore


async def test_set_and_get():
    store = RequestStore()
    await store.set("req-1", {"panel": "data"})
    assert store.get("req-1") == {"panel": "data"}


async def test_get_missing_returns_none():
    store = RequestStore()
    assert store.get("nonexistent") is None


async def test_lru_eviction():
    """Oldest entry is evicted when max_requests is reached."""
    store = RequestStore(max_requests=3)
    await store.set("a", {})
    await store.set("b", {})
    await store.set("c", {})
    assert len(store) == 3
    await store.set("d", {})  # should evict "a"
    assert len(store) == 3
    assert store.get("a") is None
    assert store.get("d") is not None


async def test_update_existing_preserves_lru_order():
    """Updating an existing key moves it to most-recently-used."""
    store = RequestStore(max_requests=2)
    await store.set("a", {"v": 1})
    await store.set("b", {"v": 2})
    # Update "a" — it becomes most recently used
    await store.set("a", {"v": 99})
    # Adding "c" should evict "b" (oldest), not "a"
    await store.set("c", {})
    assert store.get("a") == {"v": 99}
    assert store.get("b") is None
    assert store.get("c") is not None


async def test_delete():
    store = RequestStore()
    await store.set("req-1", {})
    await store.delete("req-1")
    assert store.get("req-1") is None


async def test_delete_nonexistent_is_noop():
    store = RequestStore()
    await store.delete("ghost")  # should not raise


async def test_clear():
    store = RequestStore()
    await store.set("a", {})
    await store.set("b", {})
    await store.clear()
    assert len(store) == 0


async def test_len():
    store = RequestStore(max_requests=10)
    assert len(store) == 0
    await store.set("x", {})
    assert len(store) == 1


async def test_contains():
    store = RequestStore()
    await store.set("req-1", {})
    assert "req-1" in store
    assert "other" not in store


async def test_max_requests_property():
    store = RequestStore(max_requests=42)
    assert store.max_requests == 42


async def test_concurrent_writes():
    """Multiple concurrent set() calls must not corrupt the store."""
    import asyncio

    store = RequestStore(max_requests=100)

    async def write(i: int) -> None:
        await store.set(f"req-{i}", {"index": i})

    await asyncio.gather(*[write(i) for i in range(50)])
    assert len(store) == 50
    for i in range(50):
        assert store.get(f"req-{i}") == {"index": i}
