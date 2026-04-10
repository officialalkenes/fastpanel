"""
fastpanel.toolbar
~~~~~~~~~~~~~~~~~

Toolbar orchestrator — owns the list of active panels, coordinates their
lifecycle calls, and renders the toolbar HTML snippet.

``ToolbarOrchestrator`` is the central coordinator. It is instantiated once
per ``FastPanel`` instance (not per request) and its methods are called by
the middleware for every request.

Responsibilities:
  1. Build the list of active panel instances from config
  2. Call ``panel.enable(config)`` once at startup
  3. Per-request: call ``reset()`` → ``process_request()`` on all panels
  4. Per-request: call ``process_response()`` on all panels, measuring overhead
  5. Collect ``get_data()`` from all panels into a single dict
  6. Render the toolbar HTML snippet via Jinja2
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jinja2 import Environment, FileSystemLoader
from starlette.requests import Request
from starlette.responses import Response

from fastpanel.panels.base import AbstractPanel

if TYPE_CHECKING:
    from fastpanel.config import FastPanelConfig

# Path to the templates directory, resolved relative to this file.
_TEMPLATES_DIR = Path(__file__).parent / "templates"


def _build_default_panels(config: FastPanelConfig) -> list[type[AbstractPanel]]:
    """Return the list of default panel classes based on config flags.

    Import errors for optional panels (SQL, Cache) are handled here —
    if a panel class can be imported, it's included. The panel's own
    ``enable()`` method will disable it if the dep is missing at runtime.

    Args:
        config: The active ``FastPanelConfig`` instance.

    Returns:
        List of panel *classes* (not instances).
    """
    from fastpanel.panels.headers import HeadersPanel
    from fastpanel.panels.logging import LoggingPanel
    from fastpanel.panels.performance import PerformancePanel
    from fastpanel.panels.request import RequestPanel
    from fastpanel.panels.response import ResponsePanel

    panels: list[type[AbstractPanel]] = [
        RequestPanel,
        ResponsePanel,
        PerformancePanel,
        HeadersPanel,
    ]

    if config.show_logging:
        panels.append(LoggingPanel)

    if config.show_sql:
        from fastpanel.panels.sql import SQLPanel
        panels.append(SQLPanel)

    if config.show_cache:
        from fastpanel.panels.cache import CachePanel
        panels.append(CachePanel)

    return panels


class ToolbarOrchestrator:
    """Coordinates all panels across the request/response lifecycle.

    This class is instantiated once at ``FastPanel`` construction time and
    shared across all requests (it is not per-request state). Panel instances
    are owned by this orchestrator and reused across requests — the ``reset()``
    lifecycle method handles per-request state cleanup.

    Args:
        config: The active ``FastPanelConfig`` instance.
    """

    def __init__(self, config: FastPanelConfig) -> None:
        self._config = config
        self._jinja = Environment(
            loader=FileSystemLoader(str(_TEMPLATES_DIR)),
            autoescape=True,
        )
        # Build and enable panel instances.
        panel_classes = config.panels or _build_default_panels(config)
        panel_classes = list(panel_classes) + list(config.extra_panels)

        # Instantiate and enable each panel.
        self._panels: list[AbstractPanel] = []
        for cls in panel_classes:
            instance = cls()
            instance.enable(config)
            # Only keep panels that successfully enabled themselves.
            if instance.enabled:
                self._panels.append(instance)

    @property
    def panels(self) -> list[AbstractPanel]:
        """The list of active, enabled panel instances."""
        return self._panels

    async def process_request(self, request: Request) -> None:
        """Reset and activate all panels for a new incoming request.

        Calls ``reset()`` then ``process_request()`` on every active panel.
        Errors in individual panels are swallowed — one broken panel must not
        crash the whole toolbar or the user's request.

        Args:
            request: The incoming Starlette ``Request`` object.
        """
        for panel in self._panels:
            try:
                panel.reset()
                await panel.process_request(request)
            except Exception:
                # Log the error but don't propagate — a panel failure must
                # never affect the user's application response.
                import logging
                logging.getLogger("fastpanel").exception(
                    "Panel %s failed during process_request", panel.panel_id
                )

    async def process_response(
        self, request: Request, response: Response
    ) -> None:
        """Finalise all panels for the completed response.

        Calls ``process_response()`` on every active panel and measures the
        total time spent, injecting it into the PerformancePanel as overhead.

        Args:
            request: The incoming Starlette ``Request`` object.
            response: The outgoing Starlette ``Response`` object.
        """
        overhead_start = time.perf_counter()

        for panel in self._panels:
            try:
                await panel.process_response(request, response)
            except Exception:
                import logging
                logging.getLogger("fastpanel").exception(
                    "Panel %s failed during process_response", panel.panel_id
                )

        overhead_ms = (time.perf_counter() - overhead_start) * 1000

        # Inject overhead measurement into the PerformancePanel if present.
        for panel in self._panels:
            if hasattr(panel, "set_panel_overhead"):
                panel.set_panel_overhead(overhead_ms)  # type: ignore[attr-defined]
                break

    def collect_data(self) -> dict[str, Any]:
        """Collect panel data from all active panels.

        Returns:
            Dict mapping ``panel_id`` → panel data dict for every active panel.
        """
        return {panel.panel_id: panel.get_data() for panel in self._panels}

    def render_toolbar_html(self, request_id: str) -> str:
        """Render the toolbar HTML snippet to inject into the page.

        Renders ``templates/toolbar.html`` with the request ID and mount path
        as template variables.

        Args:
            request_id: The UUID4 request identifier.

        Returns:
            Rendered HTML string ready for injection before ``</body>``.
        """
        template = self._jinja.get_template("toolbar.html")
        return template.render(
            request_id=request_id,
            mount_path=self._config.mount_path,
        )
