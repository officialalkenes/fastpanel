"""
example/main.py
~~~~~~~~~~~~~~~

Example FastAPI application demonstrating every FastPanel feature:
SQL queries, logging, cache operations, and a realistic HTML response.

Run with:
    uvicorn example.main:app --reload

Then visit: http://localhost:8000/
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from fastpanel import FastPanel
from fastpanel.panels.cache import CacheTracker, InMemoryCache

# ─── Application setup ───────────────────────────────────────────────────────

app = FastAPI(title="FastPanel Example", version="0.1.0")
logger = logging.getLogger("example.app")

# ─── Database setup (async SQLite in-memory for the demo) ────────────────────

engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)  # type: ignore[call-overload]

# ─── Cache setup (in-memory cache wrapped with CacheTracker) ─────────────────

# Wrap the cache with CacheTracker so the Cache panel can record operations.
cache = CacheTracker(InMemoryCache())

# ─── Database initialisation ─────────────────────────────────────────────────

@app.on_event("startup")
async def startup() -> None:
    """Create demo tables and seed data on startup."""
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                price REAL NOT NULL
            )
        """))
        await conn.execute(text("""
            INSERT OR IGNORE INTO products (id, name, price) VALUES
            (1, 'Laptop Pro', 1299.99),
            (2, 'Wireless Keyboard', 79.99),
            (3, 'USB-C Hub', 49.99),
            (4, 'Mechanical Mouse', 89.99),
            (5, 'Monitor Stand', 34.99)
        """))

# ─── Routes ──────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    """Main demo page — runs SQL queries, logs, and does cache operations."""
    async with AsyncSessionLocal() as session:
        # SQL Panel: demonstrate two queries.
        result = await session.execute(text("SELECT * FROM products"))
        products = result.fetchall()
        result2 = await session.execute(
            text("SELECT COUNT(*) as total FROM products")
        )
        count = result2.scalar()

    # Cache Panel: demonstrate a miss then a hit.
    cached = await cache.get("featured_product")
    if cached is None:
        logger.warning("Cache miss for 'featured_product' — loading from DB")
        await cache.set("featured_product", products[0].name if products else "None")
        cached = await cache.get("featured_product")

    # Logging Panel: a sample warning.
    logger.warning("This is a sample WARNING log entry from the example app")

    # Build a simple HTML page.
    rows = "".join(
        f"<tr><td>{p.id}</td><td>{p.name}</td><td>${p.price:.2f}</td></tr>"
        for p in products
    )
    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>FastPanel Demo</title>
        <style>
            body {{ font-family: system-ui, sans-serif; max-width: 800px;
                   margin: 40px auto; padding: 0 20px; }}
            table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
            th {{ background: #f5f5f5; }}
            .badge {{ background: #e94560; color: white; padding: 2px 8px;
                     border-radius: 12px; font-size: 12px; }}
        </style>
    </head>
    <body>
        <h1>FastPanel Demo <span class="badge">dev</span></h1>
        <p>This page demonstrates FastPanel features. Check the toolbar in the
           bottom-right corner!</p>

        <h2>Products ({count} total)</h2>
        <table>
            <thead>
                <tr><th>ID</th><th>Name</th><th>Price</th></tr>
            </thead>
            <tbody>{rows}</tbody>
        </table>

        <h3>Cache</h3>
        <p>Featured product (from cache): <strong>{cached}</strong></p>

        <h3>What the toolbar shows</h3>
        <ul>
            <li><strong>SQL</strong>: 2 queries (SELECT * and COUNT)</li>
            <li><strong>Request</strong>: GET /</li>
            <li><strong>Response</strong>: 200 text/html</li>
            <li><strong>Logging</strong>: 1 warning (cache miss)</li>
            <li><strong>Cache</strong>: 1 miss, 1 hit</li>
            <li><strong>Performance</strong>: total time + CPU time</li>
            <li><strong>Headers</strong>: all request and response headers</li>
        </ul>
    </body>
    </html>
    """


@app.get("/api/products")
async def api_products() -> list[dict]:
    """JSON endpoint — toolbar should NOT inject HTML here."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(text("SELECT * FROM products"))
        products = result.fetchall()
    return [{"id": p.id, "name": p.name, "price": p.price} for p in products]


# ─── FastPanel mount ──────────────────────────────────────────────────────────

# Mount FastPanel AFTER all routes are defined.
# The ENVIRONMENT variable controls whether it's enabled.
# In a real app, use: os.getenv("ENVIRONMENT") == "development"
FastPanel(
    app,
    enabled=os.getenv("FASTPANEL_ENABLED", "true").lower() in {"true", "1", "yes"},
    slow_query_ms=50.0,  # Flag queries > 50ms as slow in this demo
)
