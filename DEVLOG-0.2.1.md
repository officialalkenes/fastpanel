# FastPanel v0.2.1 — Post-Release Bug Postmortem

**Date:** 2026-04-13  
**Version:** 0.2.1  
**Issues:** [#1](https://github.com/officialalkenes/fastpanel/issues/1), [#2](https://github.com/officialalkenes/fastpanel/issues/2)  
**Files changed:** `middleware.py`, `panels/request.py`, `templates/debugger.html`, `__init__.py`, `pyproject.toml`

---

## Overview

First real-world installs of v0.2.0 surfaced two bugs within hours of the release
on a live SaaS project:

1. **Every POST/PUT/PATCH request with a JSON body hung indefinitely.** The browser
   spinner never stopped. No response, no timeout, no error — just silence.

2. **The debugger UI at `/__fastpanel/` was unstyled.** After selecting a request,
   the tab bar rendered as plain HTML with no visual styling.

Both bugs were introduced in v0.1.0 and survived into v0.2.0. They were masked by
the test suite because `TestClient` (the standard Starlette test harness) abstracts
over the raw ASGI transport in a way that hides stream-consumption bugs. A real
uvicorn server with a real HTTP client revealed both immediately.

---

## Bug 1 — ASGI Receive Deadlock

### What the user saw

Any route that accepted a request body stopped responding after FastPanel was
mounted. GET requests worked fine. JSON POST requests never returned. The
connection stayed open, the client spun, and the server produced no output.

### Root cause

**ASGI's `receive` callable is a one-shot stream.** Once all `http.request` body
events have been pulled from it, further calls block — they `await` a queue that
will only receive a new item when the client sends more data or disconnects.

`RequestPanel.process_request` read the request body to capture JSON payloads
for the Request panel:

```python
# panels/request.py
if "application/json" in content_type:
    raw = await request.body()   # drains receive internally
    body = json.loads(raw) if raw else None
```

`request.body()` calls `Request.stream()`, which reads `http.request` events
from `receive` until `more_body=False`. After this call, every body event has
been consumed from the stream.

The middleware then passed the **same** `receive` callable to the downstream app:

```python
# middleware.py (before fix)
request = Request(scope, receive)
await self._toolbar.process_request(request)     # drains receive here
# ...
await self._app(scope, receive, intercept_send)  # BUG: receive is exhausted
```

FastAPI creates its own `Request(scope, receive)` inside the route handler.
Pydantic model binding calls `await request.body()` on it. Starlette calls
`receive()` again. But the queue is empty.

### Why it hangs instead of returning an empty body

This is the part that makes the bug dangerous rather than just incorrect.

You might expect the second read to immediately return `b""` (empty body) and
let the route handler fail with a 422 Unprocessable Entity. Instead, it **blocks
forever.**

uvicorn's HTTP/1.1 protocol handler feeds body data into an `asyncio.Queue`.
Once the `more_body=False` event has been dequeued, the queue is empty. The next
`await receive()` call suspends, waiting for something to be added to the queue.
Something gets added to the queue when the **client disconnects or sends more data**.
But the client is still connected, waiting silently for the server to respond.

```
Server                          Client
──────                          ──────
await receive()  →  [blocking]
                                [waiting for HTTP response]

Neither side moves. The connection stays open forever.
```

This is a **deadlock**. The server is blocked waiting for the client to do
something; the client is blocked waiting for the server to do something. Neither
will ever act first.

The bug only triggered for `application/json` requests because the
`if "application/json" in content_type:` guard in `RequestPanel` meant that GET
requests, form POSTs, and multipart uploads were unaffected.

### The misleading comment

The original `request.py` had this comment:

```python
# The body is consumed once here; Starlette caches it so downstream handlers
# still see the full body.
```

This is factually wrong in the most dangerous way — it sounds authoritative,
it has a plausible explanation, and it directly describes the mechanism that
should prevent the bug. Starlette *does* cache `request.body()` — but on the
`Request` **instance**, not on the `scope`. Middleware creates one instance;
the route handler creates a completely separate instance. They do not share
the cache. The comment was the conceptual error that allowed the bug to pass
code review.

### The fix

Buffer the entire request body upfront in `_instrument` — before any panel code
runs — then replace `receive` with a stateless `replay_receive` that always
returns the cached bytes:

```python
# middleware.py — _instrument() (after fix)

# Drain all body events from the real receive upfront.
_req_chunks: list[bytes] = []
while True:
    _msg = await receive()
    if _msg["type"] == "http.disconnect":
        await self._app(scope, receive, send)
        return
    if _msg["type"] == "http.request":
        _chunk = _msg.get("body", b"")
        if _chunk:
            _req_chunks.append(_chunk)
        if not _msg.get("more_body", False):
            break

_cached_body = b"".join(_req_chunks)

async def replay_receive() -> Any:
    """Return the cached body on every call.

    Stateless and re-entrant. Any number of Request instances — panels,
    route handler, nested middleware — can call request.body() against
    this and each gets the full body without blocking.
    """
    return {"type": "http.request", "body": _cached_body, "more_body": False}

request = Request(scope, replay_receive)
await self._toolbar.process_request(request)   # safe: replay_receive is re-entrant
# ...
await self._app(scope, replay_receive, intercept_send)   # fixed
```

Key properties of `replay_receive`:

- **Stateless.** No flag, no counter. Calling it twice returns the same body both
  times. This is safe because each `Request.body()` caller reads until it gets
  `more_body=False`, which is always true here — so each caller exits after
  exactly one `receive()` call.
- **Zero-copy for GET requests.** GET bodies are empty. The upfront drain reads a
  single `{"type": "http.request", "body": b"", "more_body": False}` event and
  completes immediately. `_cached_body` is `b""`.
- **No regression for non-JSON POSTs.** Large bodies (file uploads, form data) are
  now buffered rather than streamed, but they were already being buffered by the
  panel on JSON POSTs. The guard `if "application/json" in content_type:` is
  retained in the panel — it just no longer matters for correctness.

### Why the test suite missed it

`TestClient` is Starlette's synchronous test harness backed by `httpx`. It
constructs the ASGI `receive` callable from an in-memory byte buffer, not from a
real TCP socket. When the buffer is exhausted, subsequent `receive()` calls
return `{"type": "http.disconnect"}` immediately rather than blocking. Starlette's
`Request.stream()` raises `ClientDisconnect`, which propagates up and causes the
test to fail with an exception — not a hang. The bug surfaces only under a real
uvicorn server where `receive` can genuinely block.

A proper regression test would use `httpx.AsyncClient` with `ASGITransport` and
`asyncio.wait_for(..., timeout=2.0)` to assert the request completes within a
time bound. This is filed as a follow-up.

---

## Bug 2 — Debugger Tab Bar Unstyled

### What the user saw

Visiting `/__fastpanel/` in a browser showed the debugger layout correctly (dark
background, sidebar, header). But after clicking on a request entry to inspect
it, the tab bar at the top of the detail panel showed plain text with no visual
styling — no background, no active indicator, no borders. It looked like raw HTML.

### Root cause

`debugger.html` has a large inline `<style>` block that provides the page's core
layout and colours. It also links `toolbar.css` for supplementary styles. The
problem is that it depended on `toolbar.css` for the `.fp-tab*` classes that the
tab bar needs:

```css
/* toolbar.css — NOT in the inline <style> block */
.fp-tab {
  display: flex;
  color: var(--fp-text-muted);   /* CSS custom property */
  border-right: 1px solid var(--fp-border);
  ...
}
.fp-tab.fp-tab-active {
  border-bottom: 2px solid var(--fp-accent);
  ...
}
```

The CSS custom properties (`--fp-text-muted`, `--fp-border`, `--fp-accent`, etc.)
are declared in `toolbar.css`'s `:root` block. The inline `<style>` in
`debugger.html` uses hardcoded hex values throughout — it declares no custom
properties and therefore provides no fallback for the `var()` references in the
`.fp-tab*` rules.

In practice, `toolbar.css` does load successfully — it is served by the same
server on the same origin. But the page had an implicit hard dependency on an
external stylesheet for its core navigation element, which is fragile:

- If `toolbar.css` fails to load (cached 404, proxy misconfiguration, CSP
  violation, browser extension interference), tabs are invisible.
- There is no visual difference between "styles loaded correctly" and "styles
  missing" until the user selects a request and sees the broken tabs.
- The page's self-description ("fully self-contained debugger") did not match
  reality.

`debugger.js` dynamically injects tab elements into `#fp-main-tabs` using these
classes on request selection. Before any request is selected, the tab container
is empty, so the absence of `.fp-tab*` styles is invisible — the page looks fine.
The bug only manifested on user interaction.

### The fix

Added the complete `.fp-tab*` rule set directly to `debugger.html`'s inline
`<style>` block, using the hardcoded hex colours consistent with the rest of the
inline styles:

```css
/* debugger.html — inline <style> (added) */
.fp-tab {
  display: flex; align-items: center; gap: 5px; padding: 0 12px;
  height: 100%; font-size: 12px; font-weight: 500; color: #9e9e9e;
  cursor: pointer; white-space: nowrap; border-right: 1px solid #2a2a4e;
  transition: background 0.15s, color 0.15s; flex-shrink: 0; user-select: none;
}
.fp-tab:hover       { background: #16213e; color: #e0e0e0; }
.fp-tab.fp-tab-active { background: #16213e; color: #fff;
                        border-bottom: 2px solid #e94560; }
.fp-tab-title { font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; }
.fp-tab-badge { font-family: 'SF Mono', 'Fira Code', monospace; font-size: 10px;
                background: rgba(255,255,255,0.1); padding: 1px 5px;
                border-radius: 3px; color: #e0e0e0; }
```

The `toolbar.css` link is retained (it provides CSS variables that `.fp-tab:hover`
uses as a progressive enhancement when `toolbar.css` does load), but the page no
longer depends on it for correctness. Tabs render properly regardless of whether
`toolbar.css` loads.

---

## Lessons

**1. ASGI `receive` is a one-shot stream. Treat it that way.**  
Middleware that needs to inspect request bodies must buffer and replay, never
read and re-pass the original callable. This is not unique to FastPanel — any
ASGI middleware that touches request bodies faces the same constraint.

**2. `Request(scope, receive)` is not a shared object.**  
Two instances with the same `(scope, receive)` pair are independent readers of
the same underlying stream, not co-owners of a shared buffer. Comments claiming
"Starlette caches this" are only true within a single `Request` instance's
lifetime.

**3. `TestClient` masks stream-consumption bugs.**  
The sync `TestClient` / `httpx` test harness does not reproduce the blocking
behaviour of a real uvicorn `receive` queue. Bugs that cause `receive` to block
indefinitely appear as `ClientDisconnect` exceptions in tests rather than hangs.
Integration tests against a live server (or using `asyncio.wait_for`) are
necessary for this category of bug.

**4. Self-contained UI pages should be truly self-contained.**  
If an HTML page renders dynamic content via JavaScript using CSS classes, those
classes must be in the page's inline styles. Depending on an external stylesheet
for a dynamically rendered element creates an invisible, user-interaction-gated
failure mode.

**5. Inline comments can be load-bearing bugs.**  
The comment `"Starlette caches it so downstream handlers still see the full body"`
was not a benign inaccuracy — it was the justification that made the bug
invisible to review. Wrong comments that provide false assurance about correctness
are more dangerous than no comments at all.

---

## Files Changed

| File | Change |
|------|--------|
| `fastpanel/middleware.py` | Buffer body upfront in `_instrument`; use `replay_receive` for all callers |
| `fastpanel/panels/request.py` | Correct misleading inline comment |
| `fastpanel/templates/debugger.html` | Add `.fp-tab*` styles to inline `<style>` block |
| `fastpanel/__init__.py` | Bump `__version__` to `0.2.1` |
| `pyproject.toml` | Bump `version` to `0.2.1` |
| `CHANGELOG.md` | Document both fixes under `[0.2.1]` |
