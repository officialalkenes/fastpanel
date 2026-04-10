"""
fastpanel.panels.logging
~~~~~~~~~~~~~~~~~~~~~~~~

Logging panel — captures all Python log records emitted during a request
at WARNING level and above.

Implementation strategy: a custom ``logging.Handler`` subclass is attached
to the root logger during ``enable()``. When a log record is emitted, the
handler checks whether FastPanel is currently processing a request (via a
``contextvars.ContextVar``) and, if so, appends the record to the
request-scoped log buffer.

Using ``contextvars.ContextVar`` is the correct approach for async request
scoping — it provides per-coroutine-chain isolation without any locking,
which is exactly what we need in an asyncio event loop where multiple
requests are in-flight concurrently.
"""

from __future__ import annotations

import logging
import traceback
from contextvars import ContextVar
from typing import Any

from starlette.requests import Request
from starlette.responses import Response

from fastpanel.panels.base import AbstractPanel

# Module-level ContextVar that holds the per-request log buffer.
# Set to a list at the start of each request; reset to None after.
# Only records emitted while this is not None are captured.
_request_log_buffer: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "fastpanel_log_buffer", default=None
)


class _FastPanelLogHandler(logging.Handler):
    """Internal log handler that appends records to the request log buffer.

    This handler is attached to the root logger once (at ``enable()`` time)
    and remains attached for the lifetime of the process. It writes to
    ``_request_log_buffer`` only when a request context is active, so it
    has zero overhead when FastPanel is idle between requests.
    """

    def emit(self, record: logging.LogRecord) -> None:
        """Capture a log record into the current request's buffer.

        Args:
            record: The ``logging.LogRecord`` to capture.
        """
        buffer = _request_log_buffer.get()
        if buffer is None:
            # No active request context — don't capture.
            return

        # Format the exception traceback if present, so it's stored as a
        # plain string rather than a raw exception tuple that can't be JSON-
        # serialised.
        exc_text: str | None = None
        if record.exc_info:
            exc_text = "".join(traceback.format_exception(*record.exc_info))

        buffer.append(
            {
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
                "location": f"{record.pathname}:{record.lineno}",
                "exc_text": exc_text,
            }
        )


class LoggingPanel(AbstractPanel):
    """Captures Python log records emitted during the request.

    Only records at WARNING level and above are captured. INFO and DEBUG
    are intentionally excluded to avoid flooding the panel with noise.
    To adjust the threshold, subclass this panel and override ``LOG_LEVEL``.

    Stored data schema::

        {
            "records": [
                {
                    "level": "WARNING",
                    "logger": "myapp.views",
                    "message": "Item not found: 42",
                    "location": "/app/views.py:87",
                    "exc_text": null | "Traceback..."
                }
            ],
            "total": 2,
            "warning_count": 1,
            "error_count": 1
        }
    """

    panel_id = "logging"
    title = "Logging"
    template_name = "logging.html"

    # Minimum log level to capture. WARNING is the default because lower
    # levels (DEBUG, INFO) tend to generate too much noise in dev.
    LOG_LEVEL: int = logging.WARNING

    def __init__(self) -> None:
        super().__init__()
        self._records: list[dict[str, Any]] = []
        self._handler: _FastPanelLogHandler | None = None
        # Token returned by ContextVar.set() — used to reset the context var.
        self._buffer_token: Any = None

    # Class-level singleton handler — registered once to the root logger,
    # shared across all LoggingPanel instances. This prevents duplicate records
    # when multiple panels are created (e.g. in tests).
    _class_handler: _FastPanelLogHandler | None = None

    def enable(self, config: Any) -> None:
        """Attach the log handler to the root logger (once per process).

        Uses a class-level handler singleton — safe to call multiple times.
        Subsequent calls are no-ops.

        Args:
            config: The active ``FastPanelConfig`` instance.
        """
        if LoggingPanel._class_handler is not None:
            # Handler already registered — nothing to do.
            return
        handler = _FastPanelLogHandler(level=self.LOG_LEVEL)
        LoggingPanel._class_handler = handler
        self._handler = handler
        # Attach to the root logger so we capture records from all loggers.
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)

    def reset(self) -> None:
        """Clear the captured records for a new request."""
        self._records = []

    async def process_request(self, request: Request) -> None:
        """Open the request log buffer to start capturing records.

        Sets the ``ContextVar`` to a new list — from this point, any
        log record emitted by any logger (at WARNING+) will be captured
        into this buffer until ``process_response()`` closes it.

        Args:
            request: The incoming Starlette ``Request`` object.
        """
        # Create a fresh buffer and set the ContextVar to point to it.
        # We hold the token so we can reset it cleanly in process_response.
        self._records = []
        self._buffer_token = _request_log_buffer.set(self._records)

    async def process_response(self, request: Request, response: Response) -> None:
        """Close the request log buffer.

        Resets the ContextVar so subsequent log records are not captured.

        Args:
            request: The incoming Starlette ``Request`` object.
            response: The outgoing Starlette ``Response`` object.
        """
        if self._buffer_token is not None:
            _request_log_buffer.reset(self._buffer_token)
            self._buffer_token = None

    def get_stats(self) -> str:
        """Return the warning/error count as the badge text (e.g. ``"2 ⚠"``)."""
        count = len(self._records)
        if count == 0:
            return "0"
        return f"{count} ⚠"

    def get_data(self) -> dict[str, Any]:
        """Return the full log capture."""
        warning_count = sum(1 for r in self._records if r["level"] == "WARNING")
        error_count = sum(
            1 for r in self._records if r["level"] in {"ERROR", "CRITICAL"}
        )
        return {
            "records": list(self._records),
            "total": len(self._records),
            "warning_count": warning_count,
            "error_count": error_count,
        }
