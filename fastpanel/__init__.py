"""
fastpanel
~~~~~~~~~

A developer debug toolbar for FastAPI.

Quickstart::

    from fastapi import FastAPI
    from fastpanel import FastPanel

    app = FastAPI()
    FastPanel(app, enabled=True)

That's it. Visit any HTML page in your app and the toolbar will appear
in the bottom-right corner.

⚠️  **Security**: Never enable FastPanel in production. Set ``enabled=True``
only in your local development environment, gated by an environment variable::

    import os
    FastPanel(app, enabled=os.getenv("DEBUG", "false").lower() == "true")

Public API:
  - ``FastPanel``  — main entry point, wraps a FastAPI app
  - ``FastPanelConfig``  — configuration dataclass (for advanced use)

Optional (for the Cache panel):
  - ``CacheTracker``  — wraps a cache backend for cache event tracking
  - ``InMemoryCache``  — simple in-memory cache for development/testing
"""

from __future__ import annotations

from typing import Any

from fastpanel.config import FastPanelConfig

__version__ = "0.1.0"
__all__ = ["FastPanel", "FastPanelConfig"]

# Lazily export CacheTracker and InMemoryCache — they live in panels.cache but
# are part of the public surface for users who want cache instrumentation.
def __getattr__(name: str) -> Any:
    if name == "CacheTracker":
        from fastpanel.panels.cache import CacheTracker
        return CacheTracker
    if name == "InMemoryCache":
        from fastpanel.panels.cache import InMemoryCache
        return InMemoryCache
    raise AttributeError(f"module 'fastpanel' has no attribute {name!r}")


class FastPanel:
    """Mount the FastPanel debug toolbar onto a FastAPI application.

    This is the single public entry point for FastPanel. Instantiating it
    is all a developer needs to do — everything else is automatic.

    Args:
        app: The ``FastAPI`` (or Starlette) application to instrument.
        enabled: Master enable switch. Defaults to ``False``. Set to
            ``True`` only in development. Can also be set via the
            ``FASTPANEL_ENABLED`` environment variable.
        **kwargs: Any additional ``FastPanelConfig`` fields as keyword
            arguments (e.g. ``slow_query_ms=50``, ``mount_path="/__dev"``).

    Example::

        from fastapi import FastAPI
        from fastpanel import FastPanel
        import os

        app = FastAPI()

        # Enable only in development
        FastPanel(app, enabled=os.getenv("ENVIRONMENT") == "development")

    Example with custom config::

        FastPanel(
            app,
            enabled=True,
            slow_query_ms=50.0,
            store_max_requests=200,
            excluded_paths=["/health", "/metrics"],
        )
    """

    def __init__(self, app: Any, enabled: bool = False, **kwargs: Any) -> None:
        # Build the config — merge enabled kwarg with any other config kwargs.
        kwargs["enabled"] = enabled
        self._config = FastPanelConfig.from_kwargs(**kwargs)

        if not self._config.enabled:
            # Fast path: don't touch the app at all when disabled.
            # The app is stored for reference but nothing is mounted.
            self._app = app
            return

        self._app = app
        self._mount(app)

    def _mount(self, app: Any) -> None:
        """Mount middleware and router onto *app*.

        This method performs all the wiring — it's called only when enabled.
        Separating it from ``__init__`` keeps the constructor readable and
        makes the disabled fast-path obvious.

        Args:
            app: The FastAPI application to instrument.
        """
        from fastpanel.middleware import FastPanelMiddleware
        from fastpanel.router import build_router
        from fastpanel.store import RequestStore
        from fastpanel.toolbar import ToolbarOrchestrator

        # Create shared state objects.
        store = RequestStore(max_requests=self._config.store_max_requests)
        toolbar = ToolbarOrchestrator(self._config)

        # Mount the internal API router.
        router = build_router(self._config, store)
        app.include_router(router, prefix=self._config.mount_path)

        # Add the middleware. Starlette/FastAPI middleware is added in reverse
        # order — the last-added middleware runs first. We add FastPanel last
        # so it wraps everything and sees the full request/response.
        app.add_middleware(
            FastPanelMiddleware,
            config=self._config,
            store=store,
            toolbar=toolbar,
        )

    @property
    def config(self) -> FastPanelConfig:
        """The active configuration for this FastPanel instance."""
        return self._config
