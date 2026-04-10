"""
fastpanel.router
~~~~~~~~~~~~~~~~

Internal FastAPI router for the FastPanel debug API and static assets.

Mounts at ``config.mount_path`` (default ``/__fastpanel``) with two routes:

  GET /__fastpanel/api/{request_id}
      Returns JSON panel data for the given request ID.
      Returns 404 if the request ID is not found in the store.
      Returns 404 (not 403) if FastPanel is disabled — this intentional:
      a 403 would reveal that FastPanel is installed; a 404 does not.

  GET /__fastpanel/static/{filename}
      Serves static files (toolbar.css, toolbar.js) from the built-in
      ``fastpanel/static/`` directory.
      Returns 404 if FastPanel is disabled.

Security note: All routes in this router check ``config.enabled`` and
return 404 if disabled. The ``request_id`` is a UUID4 — unpredictable
and not enumerable — so panel data cannot be accessed by guessing IDs.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse
from starlette.responses import Response

from fastpanel.config import FastPanelConfig
from fastpanel.store import RequestStore

# Path to the bundled static assets directory.
_STATIC_DIR = Path(__file__).parent / "static"

# Allowed static file names — whitelist rather than allowing arbitrary file
# traversal. Even though we serve from a controlled directory, defence-in-depth.
_ALLOWED_STATIC = frozenset({"toolbar.css", "toolbar.js"})


def build_router(config: FastPanelConfig, store: RequestStore) -> APIRouter:
    """Build and return the FastPanel internal API router.

    The router is constructed with captured references to ``config`` and
    ``store`` via closures — no global state.

    Args:
        config: The active ``FastPanelConfig`` instance.
        store: The ``RequestStore`` that holds per-request panel data.

    Returns:
        A configured ``APIRouter`` ready to include in a FastAPI app.
    """
    router = APIRouter()

    @router.get("/api/{request_id}")
    async def get_panel_data(request_id: str) -> JSONResponse:
        """Return panel data for a specific request.

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
        """Serve a static asset file.

        Only ``toolbar.css`` and ``toolbar.js`` are served. All other
        filenames return 404, regardless of whether they exist on disk.

        Args:
            filename: The static file name to serve.

        Returns:
            The file content, or 404 if not found/disabled/not allowed.
        """
        if not config.enabled:
            return Response(status_code=404)

        if filename not in _ALLOWED_STATIC:
            return Response(status_code=404)

        file_path = _STATIC_DIR / filename
        if not file_path.is_file():
            return Response(status_code=404)

        # Determine content type from extension.
        media_type = "text/css" if filename.endswith(".css") else "application/javascript"
        return FileResponse(path=str(file_path), media_type=media_type)

    return router
