"""
fastpanel.panels.request
~~~~~~~~~~~~~~~~~~~~~~~~

Request panel — captures everything about the incoming HTTP request:
method, URL, path parameters, query parameters, headers, cookies,
and body (if the content type is application/json).

This panel is purely observational — it reads from the ``Request`` object
and stores a snapshot. No side effects on the request.
"""

from __future__ import annotations

import json
from typing import Any

from starlette.requests import Request
from starlette.responses import Response

from fastpanel.panels.base import AbstractPanel


class RequestPanel(AbstractPanel):
    """Captures details of the incoming HTTP request.

    Stored data schema::

        {
            "method": "GET",
            "url": "http://localhost:8000/items/42",
            "path": "/items/42",
            "path_params": {"item_id": "42"},
            "query_params": {"q": "hello"},
            "headers": {"host": "localhost:8000", ...},
            "cookies": {"session": "abc123"},
            "body": null | {...}   # parsed JSON body or null
        }
    """

    panel_id = "request"
    title = "Request"
    template_name = "request.html"

    def __init__(self) -> None:
        super().__init__()
        self._data: dict[str, Any] = {}

    def reset(self) -> None:
        """Clear captured request data."""
        self._data = {}

    async def process_request(self, request: Request) -> None:
        """Snapshot the incoming request.

        We read the body only if the content type is ``application/json``
        to avoid buffering large binary uploads into memory. The body is
        consumed once here; Starlette caches it so downstream handlers
        still see the full body.

        Args:
            request: The incoming Starlette ``Request`` object.
        """
        body: Any = None
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                raw = await request.body()
                body = json.loads(raw) if raw else None
            except (json.JSONDecodeError, UnicodeDecodeError):
                # Malformed JSON — record it as a string so the panel still
                # shows *something* useful rather than crashing silently.
                body = "<invalid JSON>"

        self._data = {
            "method": request.method,
            "url": str(request.url),
            "path": request.url.path,
            "path_params": dict(request.path_params),
            "query_params": dict(request.query_params),
            # Headers are a multi-dict; collapse to regular dict (last value wins
            # for duplicate keys, which is acceptable for display purposes).
            "headers": dict(request.headers),
            "cookies": dict(request.cookies),
            "body": body,
        }

    async def process_response(self, request: Request, response: Response) -> None:
        """No-op — the request panel has nothing to do at response time."""

    def get_stats(self) -> str:
        """Return the HTTP method as the badge text (e.g. ``"GET"``)."""
        return self._data.get("method", "?")

    def get_data(self) -> dict[str, Any]:
        """Return the full captured request snapshot."""
        return self._data
