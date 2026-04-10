"""Tests for the RequestPanel."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

from fastpanel.panels.request import RequestPanel


def _make_mock_request(
    method: str = "GET",
    url: str = "http://localhost/items/42",
    path: str = "/items/42",
    path_params: dict | None = None,
    query_params: dict | None = None,
    headers: dict | None = None,
    cookies: dict | None = None,
    body: bytes = b"",
    content_type: str = "",
) -> MagicMock:
    """Build a mock Starlette Request for panel testing."""
    req = MagicMock()
    req.method = method

    url_mock = MagicMock()
    url_mock.__str__ = MagicMock(return_value=url)
    url_mock.path = path
    req.url = url_mock

    req.path_params = path_params or {}
    req.query_params = query_params or {}
    req.cookies = cookies or {}

    all_headers = {"host": "localhost"}
    if content_type:
        all_headers["content-type"] = content_type
    if headers:
        all_headers.update(headers)
    req.headers = all_headers

    req.body = AsyncMock(return_value=body)
    return req


async def test_captures_method():
    panel = RequestPanel()
    req = _make_mock_request(method="POST")
    await panel.process_request(req)
    assert panel.get_data()["method"] == "POST"
    assert panel.get_stats() == "POST"


async def test_captures_url_and_path():
    panel = RequestPanel()
    req = _make_mock_request(url="http://localhost/items/42", path="/items/42")
    await panel.process_request(req)
    data = panel.get_data()
    assert data["url"] == "http://localhost/items/42"
    assert data["path"] == "/items/42"


async def test_captures_query_params():
    panel = RequestPanel()
    req = _make_mock_request(query_params={"q": "hello", "page": "1"})
    await panel.process_request(req)
    assert panel.get_data()["query_params"] == {"q": "hello", "page": "1"}


async def test_captures_json_body():
    body = json.dumps({"name": "Alice"}).encode()
    panel = RequestPanel()
    req = _make_mock_request(
        method="POST", body=body, content_type="application/json"
    )
    await panel.process_request(req)
    assert panel.get_data()["body"] == {"name": "Alice"}


async def test_non_json_body_is_null():
    panel = RequestPanel()
    req = _make_mock_request(method="POST", body=b"some binary", content_type="text/plain")
    await panel.process_request(req)
    assert panel.get_data()["body"] is None


async def test_invalid_json_body_recorded_as_string():
    panel = RequestPanel()
    req = _make_mock_request(
        method="POST", body=b"not json{{{", content_type="application/json"
    )
    await panel.process_request(req)
    assert panel.get_data()["body"] == "<invalid JSON>"


async def test_reset_clears_data():
    panel = RequestPanel()
    req = _make_mock_request(method="DELETE")
    await panel.process_request(req)
    assert panel.get_data()["method"] == "DELETE"
    panel.reset()
    assert panel.get_data() == {}


async def test_get_stats_returns_question_mark_before_capture():
    panel = RequestPanel()
    assert panel.get_stats() == "?"


async def test_panel_enabled_by_default():
    panel = RequestPanel()
    assert panel.enabled is True


async def test_panel_id_and_title():
    assert RequestPanel.panel_id == "request"
    assert RequestPanel.title == "Request"
