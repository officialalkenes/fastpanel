"""
fastpanel.panels.base
~~~~~~~~~~~~~~~~~~~~~

Abstract base class for all FastPanel panels.

Every panel in FastPanel — SQL, Request, Response, Performance, etc. — is a
subclass of ``AbstractPanel``. The middleware calls the panel lifecycle methods
at the right points in the request/response cycle, and the toolbar orchestrator
calls ``get_stats()`` and ``get_data()`` to build the toolbar UI.

Panel lifecycle (called by middleware):

1. ``enable(config)``       — called once at startup; set up listeners/hooks
2. ``process_request(req)`` — called when a request arrives; capture request-level data
3. ``process_response(req, resp)`` — called after the response is built; capture response data
4. ``get_stats()``          — returns a short summary string for the panel tab badge
5. ``get_data()``           — returns the full panel data dict for the toolbar API

All lifecycle methods are async because panel hooks may need to await I/O
(e.g. fetching cache stats). Panels that don't need async can just return
their result directly — Python will handle it correctly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from starlette.requests import Request
from starlette.responses import Response


class AbstractPanel(ABC):
    """Base class for all FastPanel panels.

    Subclass this to build a custom panel::

        from fastpanel.panels.base import AbstractPanel

        class MyPanel(AbstractPanel):
            panel_id = "my_panel"
            title = "My Panel"

            async def process_request(self, request: Request) -> None:
                self._data = {"custom": "value"}

            def get_stats(self) -> str:
                return "1"

            def get_data(self) -> dict[str, Any]:
                return self._data

    Then register it::

        panel = FastPanel(app, debug=True, extra_panels=[MyPanel])

    Attributes:
        panel_id: Unique snake_case identifier used as the JSON key in the
            toolbar API response. Must be unique across all active panels.
        title: Human-readable panel name shown in the toolbar tab.
        template_name: Jinja2 template file (relative to
            ``fastpanel/templates/panels/``) used to render the panel body.
            Optional — panels without a template render as raw JSON.
        enabled: Set to ``False`` in ``enable()`` if the panel cannot
            activate (e.g. missing optional dependency). The toolbar will
            hide the tab for disabled panels.
    """

    panel_id: ClassVar[str]
    title: ClassVar[str]
    template_name: ClassVar[str | None] = None

    def __init__(self) -> None:
        self.enabled: bool = True

    def enable(self, config: Any) -> None:
        """Called once at startup to initialise the panel.

        Override this to set up event listeners, import optional dependencies,
        or perform any one-time setup. If setup fails (e.g. missing import),
        set ``self.enabled = False`` and the panel will be skipped silently.

        Args:
            config: The active ``FastPanelConfig`` instance.
        """
        ...

    async def process_request(self, request: Request) -> None:
        """Called when a new request arrives, before the route handler runs.

        Override this to capture request-phase data: headers, path params,
        start timers, attach log handlers, etc.

        Args:
            request: The incoming Starlette ``Request`` object.
        """
        ...

    async def process_response(self, request: Request, response: Response) -> None:
        """Called after the response is fully built, before it is sent.

        Override this to capture response-phase data: status code, headers,
        body size, stop timers, etc.

        Args:
            request: The incoming Starlette ``Request`` object.
            response: The outgoing Starlette ``Response`` object.
        """
        ...

    @abstractmethod
    def get_stats(self) -> str:
        """Return a short summary string for the panel tab badge.

        This string is shown next to the panel title in the toolbar.
        Examples: ``"3q 8ms"``, ``"GET"``, ``"200"``, ``"2 ⚠"``.

        Returns:
            A short human-readable status string.
        """

    @abstractmethod
    def get_data(self) -> dict[str, Any]:
        """Return the full panel data dict for the toolbar API response.

        This dict is serialised to JSON and returned from:
        ``GET /__fastpanel/api/{request_id}``

        The dict is merged into the top-level ``"panels"`` key under this
        panel's ``panel_id``.

        Returns:
            A JSON-serialisable dict containing all panel data.
        """

    def reset(self) -> None:
        """Reset panel state for a new request.

        Called by the middleware before ``process_request()`` to ensure
        panel instances don't bleed state between requests when instances
        are reused. The default implementation is a no-op; override as
        needed.
        """
        ...
