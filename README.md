# FastPanel

[![PyPI version](https://img.shields.io/pypi/v/fastpanel.svg)](https://pypi.org/project/fastpanel/)
[![Tests](https://img.shields.io/github/actions/workflow/status/officialalkenes/fastpanel/tests.yml?branch=main&label=tests)](https://github.com/officialalkenes/fastpanel/actions)
[![Coverage](https://img.shields.io/badge/coverage-92%25-brightgreen)](https://github.com/officialalkenes/fastpanel)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/downloads/)

**A developer debug toolbar for FastAPI** — see every SQL query, request detail,
log record, and cache operation in a floating in-browser panel, with zero code changes
to your routes.

<!-- SCREENSHOT -->

> Inspired by [django-debug-toolbar](https://github.com/jazzband/django-debug-toolbar),
> built for the modern async FastAPI stack.

---

## Features

| Panel | What it shows |
|-------|--------------|
| **SQL** | Every SQLAlchemy query: timing, formatted SQL, slow query highlighting (>100ms), calling location |
| **Request** | Method, URL, path/query params, headers, cookies, JSON body |
| **Response** | Status code, headers, content type, size |
| **Performance** | Total wall time, CPU time, panel overhead |
| **Logging** | All Python `logging` records at WARNING+ during the request |
| **Cache** | Hit/miss/set/delete events, hit rate, per-operation log |
| **Headers** | Full request and response header tables |

- Zero overhead in production (`enabled=False` is a pure pass-through)
- Two-line mount — no route decorators, no config files
- Async-native — works with `asyncio`, `asyncpg`, `aiosqlite`
- Pluggable custom panels via `AbstractPanel`
- No frontend build step — vanilla HTML/CSS/JS

---

## Installation

```bash
pip install fastpanel

# With SQLAlchemy support (SQL panel):
pip install fastpanel[sqlalchemy]

# With Redis support (Cache panel):
pip install fastpanel[redis]

# Everything:
pip install fastpanel[all]
```

Or with Poetry:

```bash
poetry add fastpanel
poetry add fastpanel[sqlalchemy]
```

---

## Quickstart

```python
from fastapi import FastAPI
from fastpanel import FastPanel
import os

app = FastAPI()

# Your routes here...

# Mount FastPanel — two lines, that's it.
FastPanel(app, enabled=os.getenv("ENVIRONMENT") == "development")
```

Start your app and visit any HTML page. The toolbar appears in the bottom-right corner.

> **Tip**: Set the `FASTPANEL_ENABLED=true` environment variable instead of
> hardcoding `enabled=True`. That way it's impossible to accidentally enable
> it in production.

---

## Configuration

All settings can be passed to the `FastPanel` constructor or set via environment
variables (`FASTPANEL_` prefix):

| Setting | Env var | Default | Description |
|---------|---------|---------|-------------|
| `enabled` | `FASTPANEL_ENABLED` | `False` | Master switch. **Never `True` in production.** |
| `mount_path` | `FASTPANEL_MOUNT_PATH` | `/__fastpanel` | URL prefix for internal routes |
| `store_max_requests` | `FASTPANEL_STORE_MAX_REQUESTS` | `100` | Max requests in memory (LRU) |
| `show_sql` | `FASTPANEL_SHOW_SQL` | `True` | Enable SQL panel |
| `show_logging` | `FASTPANEL_SHOW_LOGGING` | `True` | Enable Logging panel |
| `show_cache` | `FASTPANEL_SHOW_CACHE` | `True` | Enable Cache panel |
| `slow_query_ms` | `FASTPANEL_SLOW_QUERY_MS` | `100.0` | SQL query slow threshold (ms) |
| `excluded_paths` | — | `[]` | URL prefixes to skip (mount_path always excluded) |
| `extra_panels` | — | `[]` | Custom panel classes to append |

```python
FastPanel(
    app,
    enabled=True,
    slow_query_ms=50.0,
    store_max_requests=200,
    excluded_paths=["/health", "/metrics"],
)
```

---

## Cache Panel — `CacheTracker`

The Cache panel requires wrapping your cache client:

```python
from fastpanel.panels.cache import CacheTracker, InMemoryCache
import redis.asyncio

# In-memory cache (development/testing):
cache = CacheTracker(InMemoryCache())

# Redis (production-like):
raw_redis = redis.asyncio.Redis.from_url("redis://localhost")
cache = CacheTracker(raw_redis)

# Use cache normally — all operations are tracked:
await cache.set("user:1", user_data)
value = await cache.get("user:1")   # recorded as a hit
await cache.delete("user:1")
```

---

## SQLAlchemy Integration

The SQL panel hooks into SQLAlchemy's global event system automatically — no
changes needed to your engine or session setup. Works with:

- `AsyncEngine` + `AsyncSession` (SQLAlchemy 2.x)
- `create_async_engine("sqlite+aiosqlite://...")` 
- `create_async_engine("postgresql+asyncpg://...")`
- Synchronous engines too

> **Note on async location tracking**: With SQLAlchemy async engines, the query
> source location (`app/models.py:42`) may show `<unknown>`. This is because
> async SQLAlchemy uses greenlets to run sync drivers, and the async call stack
> isn't visible from within the cursor execute event. This is a known limitation.
> See [DEVLOG.md](DEVLOG.md) Step 8 for details.

---

## Writing a Custom Panel

Subclass `AbstractPanel`:

```python
from fastpanel.panels.base import AbstractPanel
from starlette.requests import Request
from starlette.responses import Response
from typing import Any

class TimingPanel(AbstractPanel):
    panel_id = "timing"
    title = "Timing"

    def __init__(self) -> None:
        super().__init__()
        self._events: list[str] = []

    def reset(self) -> None:
        self._events = []

    async def process_request(self, request: Request) -> None:
        self._events.append(f"Request received: {request.url.path}")

    def get_stats(self) -> str:
        return str(len(self._events))

    def get_data(self) -> dict[str, Any]:
        return {"events": self._events}
```

Register it:

```python
FastPanel(app, enabled=True, extra_panels=[TimingPanel])
```

---

## ⚠️ Security Warning

**FastPanel must never be enabled in production.**

The toolbar exposes internal request data (headers, SQL queries, log records)
via the `/__fastpanel/api/` endpoint. While the endpoint requires a UUID4
`request_id` (not guessable), it is still sensitive data that should never be
exposed in a production environment.

**Recommended pattern:**

```python
import os

FastPanel(
    app,
    enabled=os.getenv("ENVIRONMENT") == "development"
    # or:
    # enabled=os.getenv("FASTPANEL_ENABLED", "false").lower() == "true"
)
```

Ensure `ENVIRONMENT=development` (or `FASTPANEL_ENABLED=true`) is never set in
your production environment or deployment configuration.

When `enabled=False`:
- All `/__fastpanel/` routes return `404` (not `403` — the 404 does not
  reveal that FastPanel is installed)
- The middleware is a 4-line pass-through with zero overhead
- No panel data is collected or stored

---

## How This Was Built

See [DEVLOG.md](DEVLOG.md) for the full step-by-step build narrative — from
`pyproject.toml` to the final test run. Every design decision, architectural
trade-off, and gotcha is documented.

---

## Roadmap

- [ ] WebSocket panel
- [ ] Async log streaming (live panel updates)
- [ ] Redis store backend (persist panel data across restarts)
- [ ] Tortoise-ORM support
- [ ] Browser extension version (persistent across sessions)
- [ ] Profiler panel (line-level `cProfile` integration)
- [ ] Template panel (Jinja2 render times)
- [ ] Custom panel plugin registry

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, testing instructions,
branch naming conventions, and the PR checklist.

---

## License

[MIT](LICENSE) — © 2026 officialalkenes
