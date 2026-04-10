"""
fastpanel.panels.performance
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Performance panel — measures total wall-clock request time and CPU time.

Timing model:
  - Wall time: ``time.perf_counter()`` — high-resolution monotonic clock.
    Includes I/O wait (DB queries, network calls), which is what users care
    about ("how long did the page take?").
  - CPU time: ``time.process_time()`` — measures only time the process was
    actually on the CPU. Useful for diagnosing pure computation overhead vs
    I/O-bound waiting.

Both timers start in ``process_request()`` and stop in ``process_response()``.
The panel overhead (time spent by FastPanel itself collecting data) is estimated
by measuring how long all panels' ``process_response()`` calls take — this is
done in the toolbar orchestrator and injected into this panel's data after the
fact via ``set_panel_overhead()``.
"""

from __future__ import annotations

import time
from typing import Any

from starlette.requests import Request
from starlette.responses import Response

from fastpanel.panels.base import AbstractPanel


class PerformancePanel(AbstractPanel):
    """Measures request wall time and CPU time.

    Stored data schema::

        {
            "total_ms": 42.1,          # wall-clock time for the full request
            "cpu_ms": 38.4,            # CPU time only (no I/O wait)
            "panel_overhead_ms": 1.2   # estimated FastPanel overhead
        }
    """

    panel_id = "performance"
    title = "Performance"
    template_name = "performance.html"

    def __init__(self) -> None:
        super().__init__()
        self._wall_start: float = 0.0
        self._cpu_start: float = 0.0
        self._total_ms: float = 0.0
        self._cpu_ms: float = 0.0
        self._panel_overhead_ms: float = 0.0

    def reset(self) -> None:
        """Reset all timing state for a new request."""
        self._wall_start = 0.0
        self._cpu_start = 0.0
        self._total_ms = 0.0
        self._cpu_ms = 0.0
        self._panel_overhead_ms = 0.0

    async def process_request(self, request: Request) -> None:
        """Start wall-clock and CPU timers.

        Called as early as possible in the middleware chain to capture
        total request time inclusive of route handler execution.

        Args:
            request: The incoming Starlette ``Request`` object.
        """
        self._wall_start = time.perf_counter()
        self._cpu_start = time.process_time()

    async def process_response(self, request: Request, response: Response) -> None:
        """Stop timers and compute elapsed durations.

        Args:
            request: The incoming Starlette ``Request`` object.
            response: The outgoing Starlette ``Response`` object.
        """
        wall_end = time.perf_counter()
        cpu_end = time.process_time()

        self._total_ms = (wall_end - self._wall_start) * 1000
        self._cpu_ms = (cpu_end - self._cpu_start) * 1000

    def set_panel_overhead(self, overhead_ms: float) -> None:
        """Inject the measured FastPanel overhead into the performance data.

        Called by the toolbar orchestrator after all panels' ``process_response()``
        calls have completed. This gives an approximate measure of the time
        FastPanel itself consumed during the response phase.

        Args:
            overhead_ms: Elapsed time in milliseconds for all panels'
                ``process_response()`` calls.
        """
        self._panel_overhead_ms = overhead_ms

    def get_stats(self) -> str:
        """Return total request time as the badge text (e.g. ``"42ms"``)."""
        return f"{self._total_ms:.0f}ms"

    def get_data(self) -> dict[str, Any]:
        """Return the full timing data."""
        return {
            "total_ms": round(self._total_ms, 2),
            "cpu_ms": round(self._cpu_ms, 2),
            "panel_overhead_ms": round(self._panel_overhead_ms, 2),
        }

    @property
    def total_ms(self) -> float:
        """Total wall-clock time for the request in milliseconds."""
        return self._total_ms
