"""
fastpanel.panels.sql
~~~~~~~~~~~~~~~~~~~~~

SQL panel — captures every SQLAlchemy query executed during the request,
including execution time and the calling location in user code.

Implementation strategy:

SQLAlchemy 2.x fires two core events for every SQL execution:
  - ``before_cursor_execute`` — fires just before the DB driver executes
    the query; we start a timer here.
  - ``after_cursor_execute`` — fires just after the query completes;
    we stop the timer and record the query.

Both events provide the ``connection`` object. We use a WeakKeyDictionary
to associate the start time with each connection, which is safe even if
multiple queries are in-flight on different connections (connection pool).

Request scoping uses the same ``ContextVar`` pattern as the Logging panel:
a per-request buffer is set at request start and cleared at response end.
Queries emitted outside an active request context are silently ignored.

Finding the "user code" calling location:
  We walk the call stack at query capture time and skip frames belonging
  to SQLAlchemy, asyncio, and fastpanel itself, returning the first frame
  from user application code. This gives developers "app/models.py:47"
  rather than "sqlalchemy/engine/base.py:1234".

Optional import: this panel requires ``sqlalchemy``. If SQLAlchemy is not
installed, ``enable()`` sets ``self.enabled = False`` and the panel is
skipped silently.
"""

from __future__ import annotations

import re
import time
import traceback as _traceback
import weakref
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

from starlette.requests import Request
from starlette.responses import Response

from fastpanel.panels.base import AbstractPanel

# The absolute path of the fastpanel package directory — used to skip our own
# frames in the call stack walker without matching user projects that happen to
# be named "fastpanel".
_FASTPANEL_PKG_DIR = str(__file__).replace("sql.py", "").replace("\\", "/")

if TYPE_CHECKING:
    # Only imported for type hints — the real import is guarded in enable().
    pass

# Per-request query buffer. Set to a list at request start, None otherwise.
_request_query_buffer: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "fastpanel_sql_buffer", default=None
)

# Module name substrings to skip when walking the call stack for user-code
# location. We skip library internals but NOT the project directory (which may
# also be named "fastpanel") — we use _FASTPANEL_PKG_DIR for that.
_SKIP_MODULES = frozenset(
    {
        "sqlalchemy",
        "asyncio",
        "starlette",
        "uvicorn",
        "anyio",
        "_pytest",
        "pytest",
    }
)

# SQL keywords to uppercase for display formatting.
_SQL_KEYWORDS = re.compile(
    r"\b(SELECT|FROM|WHERE|JOIN|LEFT|RIGHT|INNER|OUTER|ON|AND|OR|NOT|IN|IS|"
    r"NULL|INSERT|INTO|VALUES|UPDATE|SET|DELETE|CREATE|DROP|ALTER|TABLE|"
    r"INDEX|ORDER|BY|GROUP|HAVING|LIMIT|OFFSET|DISTINCT|AS|UNION|ALL|"
    r"EXISTS|BETWEEN|LIKE|CASE|WHEN|THEN|ELSE|END|WITH|RETURNING|"
    r"BEGIN|COMMIT|ROLLBACK|SAVEPOINT)\b",
    re.IGNORECASE,
)


def _get_user_location() -> str:
    """Walk the call stack and return the first non-library frame.

    Returns a string in the form ``"path/to/file.py:42"`` pointing to
    the location in user application code that triggered the SQL query.
    Falls back to ``"<unknown>"`` if no suitable frame is found.

    Returns:
        Source location string.
    """
    stack = _traceback.extract_stack()
    # Walk from the innermost frame outward, skipping library internals.
    for frame in reversed(stack):
        filename = frame.filename
        # Normalise to forward slashes for cross-platform consistency.
        filename = filename.replace("\\", "/")
        # Skip frames from our own package (not just any dir named "fastpanel").
        if _FASTPANEL_PKG_DIR in filename:
            continue
        # Skip frames from known library modules.
        if any(skip in filename for skip in _SKIP_MODULES):
            continue
        # Skip site-packages entirely.
        if "site-packages" in filename:
            continue
        return f"{filename}:{frame.lineno}"
    return "<unknown>"


def _format_sql(sql: str) -> str:
    """Lightly format a SQL string for readability.

    Uppercases SQL keywords. More aggressive formatting (indentation,
    line breaks) would require a full SQL parser — we keep it lightweight
    to avoid a heavy dependency.

    Args:
        sql: Raw SQL string.

    Returns:
        Formatted SQL string with keywords uppercased.
    """
    return _SQL_KEYWORDS.sub(lambda m: m.group(0).upper(), sql)


# ─── Module-level singleton listener state ───────────────────────────────────
# Listeners are registered once per process — not once per SQLPanel instance.
# This prevents duplicate event delivery when multiple SQLPanel instances exist
# (e.g. in tests). The module-level _in_flight dict is shared by all listeners.

# WeakKeyDictionary maps connection → (start_time, slow_query_ms_at_start).
# Using a module-level dict ensures the single set of listeners can write to it.
_in_flight: weakref.WeakKeyDictionary[Any, tuple[float, float]] = (
    weakref.WeakKeyDictionary()
)

# Flag to track whether we've already registered the Engine event listeners.
_listeners_active: bool = False

# Module-level reference to the current active SQLPanel instance's slow_query_ms.
# Updated in process_request() so the listener always uses the live threshold.
_active_slow_query_ms: ContextVar[float] = ContextVar(
    "fastpanel_sql_slow_ms", default=100.0
)


def _sql_listeners_registered() -> bool:
    """Return True if Engine event listeners are already registered."""
    return _listeners_active


def _register_sql_listeners(Engine: Any, event: Any) -> None:
    """Register SQLAlchemy Engine event listeners exactly once."""
    global _listeners_active
    _listeners_active = True

    @event.listens_for(Engine, "before_cursor_execute", named=True)
    def before_execute(
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        if _request_query_buffer.get() is not None:
            _in_flight[conn] = (time.perf_counter(), _active_slow_query_ms.get())

    @event.listens_for(Engine, "after_cursor_execute", named=True)
    def after_execute(
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        buffer = _request_query_buffer.get()
        if buffer is None:
            return

        entry = _in_flight.pop(conn, None)
        if entry is None:
            return

        start, slow_ms = entry
        duration_ms = (time.perf_counter() - start) * 1000
        location = _get_user_location()

        buffer.append(
            {
                "sql": statement,
                "sql_formatted": _format_sql(statement),
                "parameters": SQLPanel._serialise_params(parameters),
                "duration_ms": round(duration_ms, 3),
                "location": location,
                "is_slow": duration_ms >= slow_ms,
            }
        )


class SQLPanel(AbstractPanel):
    """Captures SQLAlchemy queries executed during the request.

    Requires the ``sqlalchemy`` package. If not installed, this panel
    disables itself silently.

    Stored data schema::

        {
            "queries": [
                {
                    "sql": "SELECT id, name FROM users WHERE id = :id_1",
                    "sql_formatted": "SELECT id, name FROM users WHERE ...",
                    "parameters": {"id_1": 42},
                    "duration_ms": 4.2,
                    "location": "app/models.py:47",
                    "is_slow": false
                }
            ],
            "total_queries": 3,
            "total_duration_ms": 8.1,
            "slow_query_ms": 100.0
        }
    """

    panel_id = "sql"
    title = "SQL"
    template_name = "sql.html"

    def __init__(self) -> None:
        super().__init__()
        self._queries: list[dict[str, Any]] = []
        self._slow_query_ms: float = 100.0
        self._buffer_token: Any = None

    def enable(self, config: Any) -> None:
        """Attach SQLAlchemy event listeners (registered once globally).

        Tries to import SQLAlchemy. If not available, disables the panel.
        Attaches listeners to the SQLAlchemy ``Engine`` class events so ALL
        engine instances are covered without user code changes.

        Listeners are registered exactly once across all SQLPanel instances
        to avoid duplicate event delivery. Subsequent calls to ``enable()``
        only update ``slow_query_ms``.

        Args:
            config: The active ``FastPanelConfig`` instance.
        """
        try:
            from sqlalchemy import event
            from sqlalchemy.engine import Engine
        except ImportError:
            self.enabled = False
            return

        self._slow_query_ms = config.slow_query_ms

        # Guard: register listeners only once. The module-level _in_flight
        # WeakKeyDictionary is shared across all instances — the ContextVar
        # provides per-request isolation.
        if _sql_listeners_registered():
            return

        _register_sql_listeners(Engine, event)

    @staticmethod
    def _serialise_params(parameters: Any) -> Any:
        """Convert SQLAlchemy query parameters to a JSON-safe form.

        SQLAlchemy may pass parameters as a dict, a list of dicts, a tuple,
        or None. We convert to a form safe for JSON serialisation.

        Args:
            parameters: Raw SQLAlchemy parameter value.

        Returns:
            JSON-serialisable representation of the parameters.
        """
        if parameters is None:
            return None
        if isinstance(parameters, dict):
            return {str(k): str(v) for k, v in parameters.items()}
        if isinstance(parameters, (list, tuple)):
            return [
                {str(k): str(v) for k, v in p.items()}
                if isinstance(p, dict)
                else str(p)
                for p in parameters
            ]
        return str(parameters)

    def reset(self) -> None:
        """Clear the query list for a new request."""
        self._queries = []

    async def process_request(self, request: Request) -> None:
        """Open the request SQL buffer.

        Also sets the per-request slow_query_ms threshold via ContextVar so the
        module-level event listener uses this panel instance's configured value.

        Args:
            request: The incoming Starlette ``Request`` object.
        """
        self._queries = []
        _active_slow_query_ms.set(self._slow_query_ms)
        self._buffer_token = _request_query_buffer.set(self._queries)

    async def process_response(self, request: Request, response: Response) -> None:
        """Close the request SQL buffer.

        Args:
            request: The incoming Starlette ``Request`` object.
            response: The outgoing Starlette ``Response`` object.
        """
        if self._buffer_token is not None:
            _request_query_buffer.reset(self._buffer_token)
            self._buffer_token = None

    def get_stats(self) -> str:
        """Return query count and total time as badge text (e.g. ``"3q 8ms"``)."""
        total_ms = sum(q["duration_ms"] for q in self._queries)
        return f"{len(self._queries)}q {total_ms:.0f}ms"

    def get_data(self) -> dict[str, Any]:
        """Return the full query capture."""
        total_duration = sum(q["duration_ms"] for q in self._queries)
        return {
            "queries": list(self._queries),
            "total_queries": len(self._queries),
            "total_duration_ms": round(total_duration, 3),
            "slow_query_ms": self._slow_query_ms,
        }
