"""Tests for the ResponsePanel."""

from __future__ import annotations

from unittest.mock import MagicMock

from fastpanel.panels.response import ResponsePanel


def _make_mock_response(
    status_code: int = 200,
    headers: dict | None = None,
) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = headers or {"content-type": "text/html; charset=utf-8"}
    return resp


async def test_captures_status_code():
    panel = ResponsePanel()
    resp = _make_mock_response(status_code=201)
    await panel.process_response(MagicMock(), resp)
    assert panel.get_data()["status_code"] == 201
    assert panel.get_stats() == "201"


async def test_captures_content_type():
    panel = ResponsePanel()
    resp = _make_mock_response(headers={"content-type": "application/json"})
    await panel.process_response(MagicMock(), resp)
    assert panel.get_data()["content_type"] == "application/json"


async def test_captures_content_length():
    panel = ResponsePanel()
    resp = _make_mock_response(
        headers={"content-type": "text/html", "content-length": "1234"}
    )
    await panel.process_response(MagicMock(), resp)
    assert panel.get_data()["content_length"] == 1234


async def test_content_length_none_when_absent():
    panel = ResponsePanel()
    resp = _make_mock_response(headers={"content-type": "text/html"})
    await panel.process_response(MagicMock(), resp)
    assert panel.get_data()["content_length"] is None


async def test_reset_clears_data():
    panel = ResponsePanel()
    resp = _make_mock_response(status_code=404)
    await panel.process_response(MagicMock(), resp)
    assert panel.get_data()["status_code"] == 404
    panel.reset()
    assert panel.get_data() == {}


async def test_get_stats_before_capture():
    panel = ResponsePanel()
    assert panel.get_stats() == "?"


async def test_panel_id_and_title():
    assert ResponsePanel.panel_id == "response"
    assert ResponsePanel.title == "Response"
