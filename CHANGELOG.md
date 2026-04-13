# Changelog

All notable changes to FastPanel will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.1] — 2026-04-13

### Fixed

- **Critical: request body deadlock** — `RequestPanel.process_request` called
  `await request.body()` which drained ASGI's one-shot `receive` stream. The
  downstream route handler then tried to read the same stream; uvicorn's
  `receive` blocked forever waiting for a disconnect event that never arrived
  (the client was still waiting for a response). The result: every
  `POST`/`PUT`/`PATCH` request with `Content-Type: application/json` hung
  indefinitely. Fixed by buffering the full request body upfront inside
  `_instrument` and replacing `receive` with a stateless `replay_receive`
  callable that returns the cached body on every call — both middleware panels
  and the downstream app read from it freely. Closes #1.

- **Debugger UI unstyled at `/__fastpanel/`** — The inline `<style>` block in
  `debugger.html` was missing the `.fp-tab`, `.fp-tab-active`, `.fp-tab-title`,
  and `.fp-tab-badge` class definitions. These were only present in
  `toolbar.css`, which defines them via CSS custom properties
  (`var(--fp-bg-lighter)` etc.) that the inline block did not declare. When a
  request was selected in the debugger, the tab bar rendered as plain unstyled
  `<div>` elements. Added the missing tab styles with hardcoded theme colors to
  `debugger.html` so the page is fully self-contained. Closes #2.

- **Stale docstring in `RequestPanel`** — corrected an incorrect inline comment
  that claimed "Starlette caches it so downstream handlers still see the full
  body." Starlette caches the body on the `Request` instance, not the `scope`;
  the comment was the root-cause misunderstanding that allowed the deadlock bug
  to go unnoticed.

## [0.2.0] — 2026-04-13

### Added

- **Standalone REST API Debugger** — a full-page inspector UI at
  `GET /__fastpanel/` for projects that serve JSON rather than HTML (the
  toolbar injection never fires for JSON responses). Lists all captured
  requests in a sidebar; click any row to inspect its full panel data across
  tabbed views (Request, Response, Performance, SQL, Logging, Cache, Headers).
- **`debugger.js`** — client-side JS for the standalone debugger. Polls
  `/__fastpanel/api/requests` every 3 s (auto-refresh toggleable), fetches
  full panel data per request, renders all panel views.
- `GET /__fastpanel/` route added to the internal router.
- `debugger.js` added to the static-file allowlist.

## [0.1.0] — 2026-04-10

### Added

- **SQL Panel** — captures SQLAlchemy queries (timing, formatted SQL, slow query
  highlighting at configurable threshold, calling location in user code)
- **Request Panel** — HTTP method, URL, path params, query params, headers,
  cookies, and JSON body
- **Response Panel** — status code, headers, content type, content length
- **Performance Panel** — wall-clock request time, CPU time, and panel overhead
- **Logging Panel** — Python `logging` records at WARNING level and above,
  with level, logger name, message, source location, and exception traceback
- **Cache Panel** — hit/miss/set/delete tracking via `CacheTracker` proxy;
  includes `InMemoryCache` for zero-dependency use
- **Headers Panel** — dedicated deep-dive view of all request and response headers
- **`FastPanel` class** — two-line mount API (`FastPanel(app, enabled=True)`)
- **`FastPanelConfig`** — full configuration dataclass with env-var overrides
  (`FASTPANEL_ENABLED`, `FASTPANEL_SLOW_QUERY_MS`, etc.)
- **Internal API** — `GET /__fastpanel/api/{request_id}` returns JSON panel data
- **Static assets** — `GET /__fastpanel/static/toolbar.{css,js}`
- **`RequestStore`** — LRU-evicting in-memory store (configurable capacity)
- **Toolbar UI** — dark-theme floating toolbar, collapsible, tab-based panel view,
  SQL syntax highlighting, session-persistent state
- **`CacheTracker`** + **`InMemoryCache`** — public API for cache instrumentation
- Zero-overhead pass-through when `enabled=False`
- 404 (not 403) for all `/__fastpanel/` routes when disabled
- Custom panel support via `extra_panels=[MyPanel]`
- Excluded paths support (auto-excludes `/__fastpanel`)

### Security

- `request_id` is UUID4 — unpredictable, not enumerable
- All `/__fastpanel/` routes return 404 when `enabled=False`
- Static file serving uses an allowlist (`toolbar.css`, `toolbar.js` only)

[Unreleased]: https://github.com/officialalkenes/fastpanel/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/officialalkenes/fastpanel/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/officialalkenes/fastpanel/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/officialalkenes/fastpanel/releases/tag/v0.1.0
