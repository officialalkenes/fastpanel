"""
fastpanel.router
~~~~~~~~~~~~~~~~

Internal FastAPI router for the FastPanel debug API, static assets, and
the standalone debugger UI.

Routes mounted at ``config.mount_path`` (default ``/__fastpanel``):

  GET /__fastpanel/
      Serves the standalone debugger UI — a full-page HTML tool that
      lists all captured API requests and lets developers inspect each
      one's panel data. This is the primary entry point for REST API apps
      that don't serve HTML pages (i.e. the toolbar injection never fires).

  GET /__fastpanel/api/requests
      Returns a JSON list of recent request summaries (method, path,
      status, duration). Used by the standalone debugger to populate the
      request list sidebar.

  GET /__fastpanel/api/{request_id}
      Returns full JSON panel data for a specific request ID.
      Returns 404 if not found or FastPanel is disabled.

  GET /__fastpanel/static/{filename}
      Serves static assets (CSS, JS). Whitelisted filenames only.
      Returns 404 if FastPanel is disabled.

Security note: All routes return 404 when disabled. Request IDs are
UUID4 — unpredictable and non-enumerable.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from jinja2 import Environment, FileSystemLoader
from starlette.responses import Response

from fastpanel.config import FastPanelConfig
from fastpanel.store import RequestStore

_STATIC_DIR = Path(__file__).parent / "static"
_TEMPLATES_DIR = Path(__file__).parent / "templates"

# Whitelist of serveable static files — no arbitrary traversal.
_ALLOWED_STATIC = frozenset({"toolbar.css", "toolbar.js", "debugger.js"})


def build_router(config: FastPanelConfig, store: RequestStore) -> APIRouter:
    """Build and return the FastPanel internal API router.

    Args:
        config: The active ``FastPanelConfig`` instance.
        store: The ``RequestStore`` that holds per-request panel data.

    Returns:
        A configured ``APIRouter`` ready to include in a FastAPI app.
    """
    router = APIRouter()
    jinja = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=True,
    )

    @router.get("/")
    async def debugger_ui() -> Response:
        """Serve the standalone debugger UI page.

        This is the main entry point for developers using FastPanel with
        a REST API app. Open ``/__fastpanel/`` in a browser tab while your
        app is running to inspect captured requests.
        """
        if not config.enabled:
            return Response(status_code=404)
        template = jinja.get_template("debugger.html")
        html = template.render(mount_path=config.mount_path)
        return HTMLResponse(content=html)

    @router.get("/api/requests")
    async def list_requests() -> JSONResponse:
        """Return summaries of all captured requests, newest first.

        Each summary contains: request_id, method, path, status_code,
        total_ms, sql_count. Used by the debugger UI sidebar.
        """
        if not config.enabled:
            return JSONResponse(status_code=404, content={"detail": "Not found"})
        return JSONResponse(content={"requests": store.list()})

    @router.get("/api/{request_id}")
    async def get_panel_data(request_id: str) -> JSONResponse:
        """Return full panel data for a specific request.

        Args:
            request_id: UUID4 string identifying the request.

        Returns:
            JSON response with panel data, or 404 if not found/disabled.
        """
        if not config.enabled:
            return JSONResponse(status_code=404, content={"detail": "Not found"})

        data = store.get(request_id)
        if data is None:
            return JSONResponse(status_code=404, content={"detail": "Not found"})

        return JSONResponse(content=data)

    @router.get("/static/{filename}")
    async def get_static(filename: str) -> Response:
        """Serve a whitelisted static asset.

        Only files in ``_ALLOWED_STATIC`` are served. All other filenames
        return 404 regardless of whether they exist on disk.

        Args:
            filename: The static file name to serve.
        """
        if not config.enabled:
            return Response(status_code=404)

        if filename not in _ALLOWED_STATIC:
            return Response(status_code=404)

        file_path = _STATIC_DIR / filename
        if not file_path.is_file():
            return Response(status_code=404)

        media_type = "text/css" if filename.endswith(".css") else "application/javascript"
        return FileResponse(path=str(file_path), media_type=media_type)

    return router
