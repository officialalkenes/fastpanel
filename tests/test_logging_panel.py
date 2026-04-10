"""Tests for the LoggingPanel."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from fastpanel.panels.logging import LoggingPanel


@pytest.fixture
def logging_panel():
    """A LoggingPanel with the handler attached, cleaned up after each test."""
    # Reset class-level handler singleton so each test gets a fresh state.
    LoggingPanel._class_handler = None
    panel = LoggingPanel()
    panel.enable(MagicMock())
    yield panel
    # Tear down: remove the handler from the root logger and clear the class ref.
    root = logging.getLogger()
    if panel._handler:
        root.removeHandler(panel._handler)
    LoggingPanel._class_handler = None


async def test_captures_warning(logging_panel: LoggingPanel):
    req, resp = MagicMock(), MagicMock()
    await logging_panel.process_request(req)
    logging.getLogger("test.logger").warning("test warning message")
    await logging_panel.process_response(req, resp)
    data = logging_panel.get_data()
    assert data["total"] == 1
    assert data["warning_count"] == 1
    assert data["records"][0]["level"] == "WARNING"
    assert data["records"][0]["message"] == "test warning message"
    assert data["records"][0]["logger"] == "test.logger"


async def test_captures_error(logging_panel: LoggingPanel):
    req, resp = MagicMock(), MagicMock()
    await logging_panel.process_request(req)
    logging.getLogger("app").error("something broke")
    await logging_panel.process_response(req, resp)
    data = logging_panel.get_data()
    assert data["error_count"] == 1


async def test_does_not_capture_info(logging_panel: LoggingPanel):
    """INFO-level records are below the threshold and should not be captured."""
    req, resp = MagicMock(), MagicMock()
    await logging_panel.process_request(req)
    logging.getLogger("app").info("just info")
    await logging_panel.process_response(req, resp)
    data = logging_panel.get_data()
    assert data["total"] == 0


async def test_does_not_capture_debug(logging_panel: LoggingPanel):
    req, resp = MagicMock(), MagicMock()
    await logging_panel.process_request(req)
    logging.getLogger("app").debug("debug noise")
    await logging_panel.process_response(req, resp)
    assert logging_panel.get_data()["total"] == 0


async def test_records_outside_request_context_not_captured(logging_panel: LoggingPanel):
    """Log records emitted outside a request context are not captured."""
    logging.getLogger("app").warning("outside request")
    assert logging_panel.get_data()["total"] == 0


async def test_get_stats_no_records(logging_panel: LoggingPanel):
    assert logging_panel.get_stats() == "0"


async def test_get_stats_with_records(logging_panel: LoggingPanel):
    req, resp = MagicMock(), MagicMock()
    await logging_panel.process_request(req)
    logging.getLogger("app").warning("w1")
    logging.getLogger("app").warning("w2")
    await logging_panel.process_response(req, resp)
    assert logging_panel.get_stats() == "2 ⚠"


async def test_reset_clears_records(logging_panel: LoggingPanel):
    req, resp = MagicMock(), MagicMock()
    await logging_panel.process_request(req)
    logging.getLogger("app").warning("test")
    await logging_panel.process_response(req, resp)
    assert logging_panel.get_data()["total"] == 1
    logging_panel.reset()
    assert logging_panel.get_data()["total"] == 0


async def test_exception_info_serialised(logging_panel: LoggingPanel):
    """Exception tracebacks are captured as plain strings."""
    req, resp = MagicMock(), MagicMock()
    await logging_panel.process_request(req)
    try:
        raise ValueError("test exception")
    except ValueError:
        logging.getLogger("app").exception("caught it")
    await logging_panel.process_response(req, resp)
    data = logging_panel.get_data()
    record = data["records"][0]
    assert record["exc_text"] is not None
    assert "ValueError" in record["exc_text"]


async def test_panel_id_and_title():
    assert LoggingPanel.panel_id == "logging"
    assert LoggingPanel.title == "Logging"
