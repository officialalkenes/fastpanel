"""Tests for the FastPanel internal API and static file routes."""

from __future__ import annotations

import re

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from httpx import ASGITransport, AsyncClient

from fastpanel import FastPanel


def _make_instrumented_app() -> FastAPI:
    """Create an app with FastPanel enabled."""
    app = FastAPI()

    @app.get("/html", response_class=HTMLResponse)
    async def html_route():
        return "<html><body>Hello</body></html>"

    FastPanel(app, enabled=True)
    return app


async def test_api_returns_panel_data():
    """GET /__fastpanel/api/{request_id} returns panel data."""
    app = _make_instrumented_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        page_resp = await client.get("/html")
        assert page_resp.status_code == 200

        match = re.search(r'data-request-id="([0-9a-f-]{36})"', page_resp.text)
        assert match, "No request_id found in toolbar HTML"
        request_id = match.group(1)

        api_resp = await client.get(f"/__fastpanel/api/{request_id}")
        assert api_resp.status_code == 200
        data = api_resp.json()

        assert data["request_id"] == request_id
        assert "panels" in data
        assert "request" in data["panels"]
        assert "response" in data["panels"]
        assert "performance" in data["panels"]


async def test_api_returns_404_for_missing_id():
    """Requesting a non-existent request_id returns 404."""
    app = _make_instrumented_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/__fastpanel/api/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


async def test_api_returns_404_when_disabled():
    """All /__fastpanel/ routes return 404 when FastPanel is disabled."""
    app = FastAPI()

    @app.get("/html", response_class=HTMLResponse)
    async def html_route():
        return "<html><body>Hello</body></html>"

    FastPanel(app, enabled=False)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/__fastpanel/api/any-id")
    assert resp.status_code == 404


async def test_static_css_served():
    """GET /__fastpanel/static/toolbar.css returns CSS content."""
    app = _make_instrumented_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/__fastpanel/static/toolbar.css")
    assert resp.status_code == 200
    assert "text/css" in resp.headers.get("content-type", "")


async def test_static_js_served():
    """GET /__fastpanel/static/toolbar.js returns JavaScript content."""
    app = _make_instrumented_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/__fastpanel/static/toolbar.js")
    assert resp.status_code == 200
    assert "javascript" in resp.headers.get("content-type", "")


async def test_static_traversal_returns_404():
    """Path traversal attempts return 404 (or 422 from FastAPI validation)."""
    app = _make_instrumented_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/__fastpanel/static/../../etc/passwd")
    assert resp.status_code in (404, 422)


async def test_static_returns_404_when_disabled():
    """Static files return 404 when FastPanel is disabled."""
    app = FastAPI()
    FastPanel(app, enabled=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/__fastpanel/static/toolbar.css")
    assert resp.status_code == 404


async def test_panel_data_includes_request_method():
    """Panel data includes the correct HTTP method from the Request panel."""
    app = _make_instrumented_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        page_resp = await client.get("/html")
        match = re.search(r'data-request-id="([0-9a-f-]{36})"', page_resp.text)
        request_id = match.group(1)
        api_resp = await client.get(f"/__fastpanel/api/{request_id}")
        data = api_resp.json()

    assert data["panels"]["request"]["method"] == "GET"


async def test_panel_data_includes_response_status():
    """Panel data includes the correct HTTP status from the Response panel."""
    app = _make_instrumented_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        page_resp = await client.get("/html")
        match = re.search(r'data-request-id="([0-9a-f-]{36})"', page_resp.text)
        request_id = match.group(1)
        api_resp = await client.get(f"/__fastpanel/api/{request_id}")
        data = api_resp.json()

    assert data["panels"]["response"]["status_code"] == 200
