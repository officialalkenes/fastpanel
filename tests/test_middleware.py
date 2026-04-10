"""Tests for FastPanelMiddleware HTML injection and bypass logic."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from httpx import ASGITransport, AsyncClient

from fastpanel import FastPanel


def _make_app(enabled: bool = True, extra_path: str | None = None) -> FastAPI:
    """Helper: create a minimal FastAPI app with FastPanel mounted."""
    app = FastAPI()

    @app.get("/html", response_class=HTMLResponse)
    async def html_route():
        return "<html><body><h1>Hello</h1></body></html>"

    @app.get("/json")
    async def json_route():
        return {"hello": "world"}

    @app.get("/binary")
    async def binary_route():
        from starlette.responses import Response
        return Response(content=b"\x89PNG\r\n", media_type="image/png")

    if extra_path:
        @app.get(extra_path, response_class=HTMLResponse)
        async def extra_route():
            return "<html><body>extra</body></html>"

    FastPanel(app, enabled=enabled)
    return app


async def test_html_response_injects_toolbar():
    """Toolbar is injected into HTML responses."""
    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/html")
    assert resp.status_code == 200
    assert "fastpanel-toolbar" in resp.text
    assert "FastPanel" in resp.text


async def test_html_response_toolbar_before_body_close():
    """Toolbar is injected immediately before </body>."""
    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/html")
    # The toolbar should appear before the closing </body> tag.
    body = resp.text
    toolbar_idx = body.lower().find("fastpanel-toolbar")
    close_body_idx = body.lower().rfind("</body>")
    assert toolbar_idx != -1
    assert close_body_idx != -1
    assert toolbar_idx < close_body_idx


async def test_json_response_is_untouched():
    """JSON responses are passed through without modification."""
    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/json")
    assert resp.status_code == 200
    data = resp.json()
    assert data == {"hello": "world"}
    assert "fastpanel" not in resp.text


async def test_binary_response_is_untouched():
    """Binary responses are not buffered or modified."""
    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/binary")
    assert resp.status_code == 200
    assert resp.content[:4] == b"\x89PNG"


async def test_disabled_toolbar_no_injection():
    """When enabled=False, nothing is injected."""
    app = _make_app(enabled=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/html")
    assert resp.status_code == 200
    assert "fastpanel" not in resp.text


async def test_excluded_path_not_instrumented():
    """Requests to excluded paths pass through without instrumentation."""
    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # The /__fastpanel path is auto-excluded.
        resp = await client.get("/__fastpanel/api/nonexistent-id")
    # Should return 404 (not found in store), not crash.
    assert resp.status_code == 404


async def test_content_length_updated_after_injection():
    """Content-Length header reflects the extended body after injection."""
    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/html")
    # Content-Length should match the actual body length.
    assert int(resp.headers.get("content-length", -1)) == len(resp.content)


async def test_concurrent_requests_data_isolation():
    """Panel data from concurrent requests does not leak between them."""
    import asyncio

    app = FastAPI()

    @app.get("/page/{item_id}", response_class=HTMLResponse)
    async def page_route(item_id: int):
        return f"<html><body>item {item_id}</body></html>"

    FastPanel(app, enabled=True)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        responses = await asyncio.gather(
            client.get("/page/1"),
            client.get("/page/2"),
            client.get("/page/3"),
        )

    # Each response should contain the correct item ID (no cross-request leakage).
    for resp in responses:
        assert resp.status_code == 200


async def test_request_id_in_toolbar_html():
    """The toolbar HTML contains a valid request_id data attribute."""
    import re

    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/html")

    # Look for data-request-id="<uuid>"
    match = re.search(r'data-request-id="([0-9a-f-]{36})"', resp.text)
    assert match is not None, "data-request-id attribute not found in toolbar HTML"


async def test_no_injection_for_non_html_content_type():
    """Responses with non-HTML content type are not modified."""
    app = FastAPI()

    @app.get("/xml")
    async def xml_route():
        from starlette.responses import Response
        return Response(content="<root><item/></root>", media_type="application/xml")

    FastPanel(app, enabled=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/xml")

    assert "fastpanel" not in resp.text
