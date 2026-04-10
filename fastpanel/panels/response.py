"""
fastpanel.panels.response
~~~~~~~~~~~~~~~~~~~~~~~~~

Response panel — captures the outgoing HTTP response: status code,
headers, content type, and response body size in bytes.

We deliberately do *not* capture the full response body — that would
require buffering potentially large responses (file downloads, streams)
just to display them in a dev toolbar. Size is enough.
"""

from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import Response

from fastpanel.panels.base import AbstractPanel


class ResponsePanel(AbstractPanel):
    """Captures details of the outgoing HTTP response.

    Stored data schema::

        {
            "status_code": 200,
            "headers": {"content-type": "application/json", ...},
            "content_type": "application/json",
            "content_length": 1234    # bytes, or null if not known
        }
    """

    panel_id = "response"
    title = "Response"
    template_name = "response.html"

    def __init__(self) -> None:
        super().__init__()
        self._data: dict[str, Any] = {}

    def reset(self) -> None:
        """Clear captured response data."""
        self._data = {}

    async def process_request(self, request: Request) -> None:
        """No-op — the response panel has nothing to do at request time."""

    async def process_response(self, request: Request, response: Response) -> None:
        """Snapshot the outgoing response.

        ``content-length`` may not be present (e.g. for streaming responses).
        We record it as ``None`` in that case rather than guessing.

        Args:
            request: The incoming Starlette ``Request`` object.
            response: The outgoing Starlette ``Response`` object.
        """
        headers = dict(response.headers)
        content_length_raw = headers.get("content-length")
        content_length: int | None = None
        if content_length_raw is not None:
            try:
                content_length = int(content_length_raw)
            except ValueError:
                pass

        self._data = {
            "status_code": response.status_code,
            "headers": headers,
            "content_type": headers.get("content-type", ""),
            "content_length": content_length,
        }

    def get_stats(self) -> str:
        """Return the HTTP status code as the badge text (e.g. ``"200"``)."""
        code = self._data.get("status_code")
        return str(code) if code is not None else "?"

    def get_data(self) -> dict[str, Any]:
        """Return the full captured response snapshot."""
        return self._data
