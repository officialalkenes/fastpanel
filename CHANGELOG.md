# Changelog

All notable changes to FastPanel will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/officialalkenes/fastpanel/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/officialalkenes/fastpanel/releases/tag/v0.1.0
