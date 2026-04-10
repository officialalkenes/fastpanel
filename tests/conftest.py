"""
Shared pytest fixtures for the FastPanel test suite.

Provides:
  - ``fastapi_app`` — a minimal FastAPI app with FastPanel mounted
  - ``enabled_config`` / ``disabled_config`` — config fixtures
  - ``store`` — a fresh RequestStore
  - ``async_client`` — an httpx AsyncClient for the test app
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from httpx import ASGITransport, AsyncClient

from fastpanel import FastPanel
from fastpanel.config import FastPanelConfig
from fastpanel.store import RequestStore


@pytest.fixture
def enabled_config() -> FastPanelConfig:
    """A FastPanelConfig with enabled=True and all panels active."""
    return FastPanelConfig(enabled=True, slow_query_ms=100.0)


@pytest.fixture
def disabled_config() -> FastPanelConfig:
    """A FastPanelConfig with enabled=False."""
    return FastPanelConfig(enabled=False)


@pytest.fixture
def store() -> RequestStore:
    """A fresh RequestStore with default capacity."""
    return RequestStore(max_requests=100)


@pytest.fixture
def fastapi_app() -> FastAPI:
    """Minimal FastAPI app with FastPanel mounted (enabled=True).

    Routes:
      GET /html  → returns a simple HTML page
      GET /json  → returns a JSON response
      GET /warn  → emits a warning log and returns HTML
    """
    app = FastAPI()

    @app.get("/html", response_class=HTMLResponse)
    async def html_route():
        return "<html><body><h1>Hello</h1></body></html>"

    @app.get("/json")
    async def json_route():
        return {"hello": "world"}

    @app.get("/warn", response_class=HTMLResponse)
    async def warn_route():
        import logging
        logging.getLogger("test").warning("test warning")
        return "<html><body><h1>Warn</h1></body></html>"

    FastPanel(app, enabled=True)
    return app


@pytest.fixture
async def async_client(fastapi_app: FastAPI) -> AsyncClient:
    """httpx AsyncClient wired to the test FastAPI app."""
    async with AsyncClient(
        transport=ASGITransport(app=fastapi_app), base_url="http://test"
    ) as client:
        yield client
