"""
fastpanel.middleware
~~~~~~~~~~~~~~~~~~~~~

Core ASGI middleware — the heart of FastPanel.

Responsibilities:
  1. Assign a UUID4 ``request_id`` to every incoming request
  2. Skip instrumentation entirely for excluded paths and non-enabled config
  3. Activate all panels (via ``ToolbarOrchestrator``) before the request
     is passed downstream
  4. Intercept the full response body by capturing ASGI ``body`` events
  5. If the response is HTML (``text/html``), inject the toolbar snippet
     just before ``</body>``
  6. Re-emit the (possibly modified) response body
  7. Store all panel data in the ``RequestStore`` keyed by ``request_id``

ASGI response body interception:

ASGI is a three-phase protocol: ``http.response.start`` (headers),
``http.response.body`` (body chunks), and connection close. To inject
HTML, we must:
  a. Capture all ``http.response.body`` chunks
  b. Reassemble them into a single bytes buffer
  c. Modify the buffer (inject toolbar HTML)
  d. Update ``Content-Length`` in the headers
  e. Send the modified response

This "buffer then modify" approach is the standard pattern for Starlette
middleware that needs to read/modify response bodies. It does buffer the
full response in memory, which means it's not suitable for very large
responses. We only do this for HTML responses — JSON, binary, and
streaming responses pass through without buffering.

Zero-overhead when disabled:

When ``config.enabled is False``, ``__call__`` is a 4-line pass-through.
No panel activation, no body buffering, no store writes. The middleware
adds zero measurable overhead in production.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

if TYPE_CHECKING:
    from fastpanel.config import FastPanelConfig
    from fastpanel.store import RequestStore
    from fastpanel.toolbar import ToolbarOrchestrator


class FastPanelMiddleware:
    """ASGI middleware that instruments requests and injects the toolbar.

    This middleware is installed at the ASGI level by ``FastPanel.mount()``.
    It wraps the entire application — every request passes through it.

    Args:
        app: The downstream ASGI application.
        config: The active ``FastPanelConfig`` instance.
        store: The ``RequestStore`` for persisting panel data.
        toolbar: The ``ToolbarOrchestrator`` for panel coordination.
    """

    def __init__(
        self,
        app: ASGIApp,
        config: FastPanelConfig,
        store: RequestStore,
        toolbar: ToolbarOrchestrator,
    ) -> None:
        self._app = app
        self._config = config
        self._store = store
        self._toolbar = toolbar

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        """ASGI entry point.

        For non-HTTP scopes (WebSocket, lifespan) and when disabled, pass
        through immediately. For HTTP requests, instrument and inject.

        Args:
            scope: ASGI connection scope dict.
            receive: ASGI receive callable.
            send: ASGI send callable.
        """
        # Only instrument HTTP requests.
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        # Zero-overhead pass-through when not enabled.
        if not self._config.enabled:
            await self._app(scope, receive, send)
            return

        # Check if this path is excluded from instrumentation.
        path: str = scope.get("path", "/")
        if self._is_excluded(path):
            await self._app(scope, receive, send)
            return

        # Instrument this request.
        await self._instrument(scope, receive, send)

    def _is_excluded(self, path: str) -> bool:
        """Return True if *path* starts with any excluded path prefix.

        Args:
            path: The URL path of the incoming request.

        Returns:
            True if the path should not be instrumented.
        """
        for excluded in self._config.excluded_paths:
            if path.startswith(excluded):
                return True
        return False

    async def _instrument(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        """Instrument a single HTTP request.

        Assigns a request_id, activates panels, passes the request
        downstream, intercepts the response, and stores panel data.

        Args:
            scope: ASGI connection scope dict.
            receive: ASGI receive callable.
            send: ASGI send callable.
        """
        from starlette.requests import Request

        request_id = str(uuid.uuid4())

        # ── Buffer the full request body ──────────────────────────────────────
        # ASGI's `receive` is a one-shot stream: once body events are consumed
        # the callable blocks forever waiting for the next transport event (a
        # disconnect that never arrives while the client is still waiting for a
        # response). Without this buffering, panels that call `request.body()`
        # would consume the stream and the downstream route handler would
        # deadlock trying to read a body that is already gone.
        #
        # We eagerly drain all `http.request` events here, cache the assembled
        # body, then hand every caller — middleware panels AND the app — a
        # `replay_receive` that always returns the cached bytes. Each caller
        # gets a fresh read of the full body regardless of call order.
        _req_chunks: list[bytes] = []
        while True:
            _msg = await receive()
            if _msg["type"] == "http.disconnect":
                # Client disconnected before sending the body — nothing to do.
                await self._app(scope, receive, send)
                return
            if _msg["type"] == "http.request":
                _chunk = _msg.get("body", b"")
                if _chunk:
                    _req_chunks.append(_chunk)
                if not _msg.get("more_body", False):
                    break

        _cached_body: bytes = b"".join(_req_chunks)

        async def replay_receive() -> Any:
            """Return the cached request body.

            Stateless and re-entrant: calling it multiple times (e.g. from
            nested middleware or multiple Request instances sharing the same
            scope) always yields the full body, so downstream handlers never
            see an empty or blocked read.
            """
            return {"type": "http.request", "body": _cached_body, "more_body": False}

        request = Request(scope, replay_receive)

        # Activate all panels for this request.
        await self._toolbar.process_request(request)

        # Collect the full response by intercepting ASGI send calls.
        response_started = False
        response_headers: list[tuple[bytes, bytes]] = []
        response_status: int = 200
        body_chunks: list[bytes] = []
        is_html: bool = False

        async def intercept_send(message: Message) -> None:
            nonlocal response_started, response_headers, response_status, is_html

            if message["type"] == "http.response.start":
                response_status = message.get("status", 200)
                response_headers = list(message.get("headers", []))

                # Determine early whether this is an HTML response so we know
                # whether to buffer the body or stream it through.
                for name, value in response_headers:
                    if name.lower() == b"content-type":
                        is_html = b"text/html" in value
                        break

                # Attach the request ID to every response — lets developers
                # see the ID in browser DevTools for any JSON/API response
                # and use it to look up panel data at /__fastpanel/.
                response_headers.append(
                    (b"x-fastpanel-request-id", request_id.encode())
                )

                if not is_html:
                    # Non-HTML: send with the updated headers immediately.
                    await send({
                        "type": "http.response.start",
                        "status": response_status,
                        "headers": response_headers,
                    })
                response_started = True

            elif message["type"] == "http.response.body":
                chunk: bytes = message.get("body", b"")
                more_body: bool = message.get("more_body", False)

                if not is_html:
                    # Non-HTML: stream through untouched.
                    await send(message)
                    return

                # HTML: buffer all chunks until the response is complete.
                body_chunks.append(chunk)

                if not more_body:
                    # All chunks received — assemble, modify, and send.
                    full_body = b"".join(body_chunks)
                    modified_body = await self._inject_toolbar(
                        full_body, request, response_headers, response_status, request_id
                    )

                    # Update Content-Length to reflect the injected bytes.
                    headers = MutableHeaders(raw=response_headers)
                    headers["content-length"] = str(len(modified_body))

                    # Send the (now complete) response start + body.
                    await send(
                        {
                            "type": "http.response.start",
                            "status": response_status,
                            "headers": response_headers,
                        }
                    )
                    await send(
                        {
                            "type": "http.response.body",
                            "body": modified_body,
                            "more_body": False,
                        }
                    )

        # Pass the request downstream using replay_receive so that route
        # handlers can read the body even though middleware already consumed it.
        await self._app(scope, replay_receive, intercept_send)

        # Finalise panels after the response is built.
        from starlette.responses import Response

        # Build a minimal Response object for panels that need response data.
        resp = Response(
            status_code=response_status,
            headers={
                k.decode(): v.decode()
                for k, v in response_headers
                if isinstance(k, bytes)
            },
        )
        await self._toolbar.process_response(request, resp)

        # Collect and store panel data, keyed by request_id.
        panel_data = {
            "request_id": request_id,
            "panels": self._toolbar.collect_data(),
        }
        await self._store.set(request_id, panel_data)

    async def _inject_toolbar(
        self,
        body: bytes,
        request: Any,
        headers: list[tuple[bytes, bytes]],
        status: int,
        request_id: str,
    ) -> bytes:
        """Inject the toolbar HTML snippet just before ``</body>``.

        If the body contains ``</body>``, the toolbar HTML is inserted
        immediately before it. If not (malformed HTML, partial body),
        the toolbar is appended at the end.

        Args:
            body: The full response body as bytes.
            request: The Starlette ``Request`` object.
            headers: The raw response headers list.
            status: The HTTP status code.
            request_id: The UUID4 request identifier.

        Returns:
            Modified body bytes with toolbar HTML injected.
        """
        toolbar_html = self._toolbar.render_toolbar_html(request_id)

        # Try to decode as UTF-8. If that fails (binary content disguised
        # as HTML), return the body unmodified.
        try:
            body_str = body.decode("utf-8")
        except UnicodeDecodeError:
            return body

        # Inject before </body> if present, otherwise append.
        close_body = "</body>"
        idx = body_str.lower().rfind(close_body)
        if idx != -1:
            modified = body_str[:idx] + toolbar_html + body_str[idx:]
        else:
            modified = body_str + toolbar_html

        return modified.encode("utf-8")
