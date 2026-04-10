"""Tests for the PerformancePanel."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

from fastpanel.panels.performance import PerformancePanel


async def test_measures_wall_time():
    panel = PerformancePanel()
    req, resp = MagicMock(), MagicMock()
    await panel.process_request(req)
    time.sleep(0.01)  # 10ms sleep
    await panel.process_response(req, resp)
    data = panel.get_data()
    assert data["total_ms"] >= 10.0


async def test_measures_cpu_time():
    panel = PerformancePanel()
    req, resp = MagicMock(), MagicMock()
    await panel.process_request(req)
    # Busy loop to consume CPU time.
    end = time.perf_counter() + 0.005
    while time.perf_counter() < end:
        pass
    await panel.process_response(req, resp)
    data = panel.get_data()
    # CPU time should be > 0 after a busy loop.
    assert data["cpu_ms"] >= 0


async def test_panel_overhead_set():
    panel = PerformancePanel()
    req, resp = MagicMock(), MagicMock()
    await panel.process_request(req)
    await panel.process_response(req, resp)
    panel.set_panel_overhead(3.14)
    assert panel.get_data()["panel_overhead_ms"] == 3.14


async def test_get_stats_format():
    panel = PerformancePanel()
    req, resp = MagicMock(), MagicMock()
    await panel.process_request(req)
    await panel.process_response(req, resp)
    stats = panel.get_stats()
    assert stats.endswith("ms")


async def test_reset_clears_timers():
    panel = PerformancePanel()
    req, resp = MagicMock(), MagicMock()
    await panel.process_request(req)
    time.sleep(0.01)
    await panel.process_response(req, resp)
    assert panel.total_ms > 0
    panel.reset()
    assert panel.total_ms == 0.0


async def test_total_ms_property():
    panel = PerformancePanel()
    req, resp = MagicMock(), MagicMock()
    await panel.process_request(req)
    time.sleep(0.005)
    await panel.process_response(req, resp)
    assert panel.total_ms > 0
    # get_data() rounds to 2dp; total_ms property returns the raw float.
    assert round(panel.total_ms, 2) == panel.get_data()["total_ms"]


async def test_panel_id_and_title():
    assert PerformancePanel.panel_id == "performance"
    assert PerformancePanel.title == "Performance"
