"""Tests for the SQLPanel using an in-memory async SQLite database."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

pytest.importorskip("sqlalchemy", reason="sqlalchemy not installed")
pytest.importorskip("aiosqlite", reason="aiosqlite not installed")

from sqlalchemy import Column, Integer, String, text  # noqa: I001 — must follow importorskip
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from fastpanel.panels.sql import SQLPanel, _format_sql


# ─── SQLAlchemy test setup ────────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    name = Column(String)


@pytest.fixture
async def engine():
    """In-memory async SQLite engine for tests."""
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
def sql_panel() -> SQLPanel:
    """A SQLPanel with SQLAlchemy event listeners attached."""
    panel = SQLPanel()
    config = MagicMock()
    config.slow_query_ms = 100.0
    panel.enable(config)
    return panel


# ─── Tests ────────────────────────────────────────────────────────────────────

async def test_captures_query(sql_panel: SQLPanel, engine):
    """Queries executed within a request context are captured."""
    req, resp = MagicMock(), MagicMock()
    await sql_panel.process_request(req)

    async with AsyncSession(engine) as session:
        await session.execute(text("SELECT 1"))

    await sql_panel.process_response(req, resp)
    data = sql_panel.get_data()
    assert data["total_queries"] >= 1


async def test_query_has_duration(sql_panel: SQLPanel, engine):
    req, resp = MagicMock(), MagicMock()
    await sql_panel.process_request(req)
    async with AsyncSession(engine) as session:
        await session.execute(text("SELECT 1"))
    await sql_panel.process_response(req, resp)
    query = sql_panel.get_data()["queries"][0]
    assert query["duration_ms"] >= 0


async def test_query_has_location(sql_panel: SQLPanel, engine):
    """Location field is present; may be '<unknown>' with async greenlet engines.

    SQLAlchemy 2.x async uses greenlets to run sync drivers — the async call
    stack is not visible from the cursor execute event, so location detection
    returns '<unknown>' for aiosqlite/asyncpg. This is a known limitation
    documented in the DEVLOG. The field always exists in the query record.
    """
    req, resp = MagicMock(), MagicMock()
    await sql_panel.process_request(req)
    async with AsyncSession(engine) as session:
        await session.execute(text("SELECT 1"))
    await sql_panel.process_response(req, resp)
    query = sql_panel.get_data()["queries"][0]
    # The "location" field must always be present (never missing from the dict).
    assert "location" in query
    # Value may be "<unknown>" with async engines due to greenlet call stack
    # isolation — see DEVLOG Step 8 for details.
    assert isinstance(query["location"], str)


async def test_query_has_formatted_sql(sql_panel: SQLPanel, engine):
    req, resp = MagicMock(), MagicMock()
    await sql_panel.process_request(req)
    async with AsyncSession(engine) as session:
        await session.execute(text("select 1"))
    await sql_panel.process_response(req, resp)
    query = sql_panel.get_data()["queries"][0]
    # Formatted SQL should have uppercase keywords
    assert "SELECT" in query["sql_formatted"]


async def test_slow_query_flagged(sql_panel: SQLPanel, engine):
    """Set slow_query_ms very low so the test query is flagged as slow."""
    sql_panel._slow_query_ms = 0.0  # 0ms threshold — everything is "slow"
    req, resp = MagicMock(), MagicMock()
    await sql_panel.process_request(req)
    async with AsyncSession(engine) as session:
        await session.execute(text("SELECT 1"))
    await sql_panel.process_response(req, resp)
    query = sql_panel.get_data()["queries"][0]
    assert query["is_slow"] is True


async def test_fast_query_not_flagged(sql_panel: SQLPanel, engine):
    """With a high threshold, queries are not flagged as slow."""
    sql_panel._slow_query_ms = 99999.0
    req, resp = MagicMock(), MagicMock()
    await sql_panel.process_request(req)
    async with AsyncSession(engine) as session:
        await session.execute(text("SELECT 1"))
    await sql_panel.process_response(req, resp)
    query = sql_panel.get_data()["queries"][0]
    assert query["is_slow"] is False


async def test_queries_outside_request_not_captured(sql_panel: SQLPanel, engine):
    """Queries executed outside a request context are not captured."""
    async with AsyncSession(engine) as session:
        await session.execute(text("SELECT 1"))
    # No process_request called — the panel should have no queries.
    assert sql_panel.get_data()["total_queries"] == 0


async def test_get_stats_format(sql_panel: SQLPanel, engine):
    req, resp = MagicMock(), MagicMock()
    await sql_panel.process_request(req)
    async with AsyncSession(engine) as session:
        await session.execute(text("SELECT 1"))
    await sql_panel.process_response(req, resp)
    stats = sql_panel.get_stats()
    assert "q" in stats
    assert "ms" in stats


async def test_reset_clears_queries(sql_panel: SQLPanel, engine):
    req, resp = MagicMock(), MagicMock()
    await sql_panel.process_request(req)
    async with AsyncSession(engine) as session:
        await session.execute(text("SELECT 1"))
    await sql_panel.process_response(req, resp)
    assert sql_panel.get_data()["total_queries"] >= 1
    sql_panel.reset()
    assert sql_panel.get_data()["total_queries"] == 0


async def test_total_duration_summed(sql_panel: SQLPanel, engine):
    req, resp = MagicMock(), MagicMock()
    await sql_panel.process_request(req)
    async with AsyncSession(engine) as session:
        await session.execute(text("SELECT 1"))
        await session.execute(text("SELECT 2"))
    await sql_panel.process_response(req, resp)
    data = sql_panel.get_data()
    assert data["total_queries"] >= 2
    total = sum(q["duration_ms"] for q in data["queries"])
    assert abs(data["total_duration_ms"] - total) < 0.01


# ─── _format_sql tests ────────────────────────────────────────────────────────

def test_format_sql_uppercases_keywords():
    result = _format_sql("select id from users where id = 1")
    assert "SELECT" in result
    assert "FROM" in result
    assert "WHERE" in result


def test_format_sql_preserves_values():
    result = _format_sql("select * from users where name = 'alice'")
    assert "'alice'" in result


async def test_panel_id_and_title():
    assert SQLPanel.panel_id == "sql"
    assert SQLPanel.title == "SQL"
