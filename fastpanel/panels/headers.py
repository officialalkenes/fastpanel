"""
fastpanel.panels.headers
~~~~~~~~~~~~~~~~~~~~~~~~

Headers panel — a dedicated deep-dive view of all request and response
headers, presented as clean key-value tables.

This panel intentionally duplicates some data from the Request and
Response panels. The purpose is UX: the Headers panel gives you a
focused, full-width view of all headers without the noise of body,
query params, etc. It's the panel you reach for when debugging CORS,
authentication, or caching headers.
"""

from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import Response

from fastpanel.panels.base import AbstractPanel


class HeadersPanel(AbstractPanel):
    """Deep-dive view of all request and response headers.

    Stored data schema::

        {
            "request_headers": [
                {"name": "host", "value": "localhost:8000"},
                ...
            ],
            "response_headers": [
                {"name": "content-type", "value": "text/html; charset=utf-8"},
                ...
            ],
            "total_request_headers": 8,
            "total_response_headers": 4
        }

    Headers are stored as a list of ``{"name": ..., "value": ...}`` dicts
    (rather than a plain dict) to preserve duplicate header names, which
    are technically valid in HTTP and do occur in practice (``Set-Cookie``,
    ``Vary``, etc.).
    """

    panel_id = "headers"
    title = "Headers"
    template_name = "headers.html"

    def __init__(self) -> None:
        super().__init__()
        self._request_headers: list[dict[str, str]] = []
        self._response_headers: list[dict[str, str]] = []

    def reset(self) -> None:
        """Clear captured header data."""
        self._request_headers = []
        self._response_headers = []

    async def process_request(self, request: Request) -> None:
        """Capture all request headers.

        Starlette exposes headers as a ``Headers`` object (a multi-dict).
        We use ``.items()`` to preserve duplicate keys.

        Args:
            request: The incoming Starlette ``Request`` object.
        """
        self._request_headers = [
            {"name": name, "value": value}
            for name, value in request.headers.items()
        ]

    async def process_response(self, request: Request, response: Response) -> None:
        """Capture all response headers.

        Args:
            request: The incoming Starlette ``Request`` object.
            response: The outgoing Starlette ``Response`` object.
        """
        self._response_headers = [
            {"name": name, "value": value}
            for name, value in response.headers.items()
        ]

    def get_stats(self) -> str:
        """Return the total header count as the badge text (e.g. ``"12"``)."""
        total = len(self._request_headers) + len(self._response_headers)
        return str(total)

    def get_data(self) -> dict[str, Any]:
        """Return the full header snapshot."""
        return {
            "request_headers": self._request_headers,
            "response_headers": self._response_headers,
            "total_request_headers": len(self._request_headers),
            "total_response_headers": len(self._response_headers),
        }
