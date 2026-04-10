"""
fastpanel.config
~~~~~~~~~~~~~~~~

Configuration schema for FastPanel. All settings can be provided via
constructor arguments or via environment variables with the ``FASTPANEL_``
prefix. Environment variables take lower precedence than constructor args.

Usage::

    from fastpanel import FastPanel

    panel = FastPanel(app, debug=True, slow_query_ms=50.0)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


def _env_bool(key: str, default: bool) -> bool:
    """Read a boolean from an environment variable.

    Accepts ``"true"``/``"1"``/``"yes"`` as truthy (case-insensitive).
    Anything else is falsy.

    Args:
        key: Environment variable name.
        default: Value to return when the variable is not set.

    Returns:
        Parsed boolean value.
    """
    raw = os.environ.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"true", "1", "yes"}


def _env_int(key: str, default: int) -> int:
    """Read an integer from an environment variable.

    Args:
        key: Environment variable name.
        default: Value to return when the variable is not set or not parseable.

    Returns:
        Parsed integer value, or *default* on parse failure.
    """
    raw = os.environ.get(key)
    if raw is None:
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    """Read a float from an environment variable.

    Args:
        key: Environment variable name.
        default: Value to return when the variable is not set or not parseable.

    Returns:
        Parsed float value, or *default* on parse failure.
    """
    raw = os.environ.get(key)
    if raw is None:
        return default
    try:
        return float(raw.strip())
    except ValueError:
        return default


def _env_str(key: str, default: str) -> str:
    """Read a string from an environment variable.

    Args:
        key: Environment variable name.
        default: Value to return when the variable is not set.

    Returns:
        Environment variable value, or *default*.
    """
    return os.environ.get(key, default)


@dataclass
class FastPanelConfig:
    """All configuration for a FastPanel instance.

    Constructor arguments always take precedence over environment variables.
    Environment variables are read at construction time only — mutating the
    environment after construction has no effect.

    Attributes:
        enabled: Master switch. When ``False`` the middleware is a pure
            pass-through and all ``/__fastpanel/`` routes return 404.
            **Never enable in production.** Defaults to the
            ``FASTPANEL_ENABLED`` env var, or ``False``.
        mount_path: URL prefix for all internal FastPanel routes.
            Defaults to ``"/__fastpanel"``.
        store_max_requests: Maximum number of requests whose panel data is
            retained in memory. Oldest entries are evicted when the limit is
            reached (LRU). Defaults to ``100``.
        show_sql: Enable the SQL panel. Requires ``sqlalchemy`` extra.
            Defaults to ``True``.
        show_logging: Enable the Logging panel. Defaults to ``True``.
        show_cache: Enable the Cache panel. Requires ``redis`` extra for
            Redis support. Defaults to ``True``.
        slow_query_ms: SQL queries that take longer than this threshold are
            highlighted red in the SQL panel. Defaults to ``100.0`` ms.
        panels: Explicit list of panel *classes* to activate. When ``None``
            (the default) all built-in panels are activated based on the
            ``show_*`` flags above.
        extra_panels: Additional custom panel classes to append to the
            active panel list. These are always appended after built-ins.
        excluded_paths: URL path prefixes that are never instrumented.
            The FastPanel mount path is always excluded automatically.
    """

    enabled: bool = field(
        default_factory=lambda: _env_bool("FASTPANEL_ENABLED", False)
    )
    mount_path: str = field(
        default_factory=lambda: _env_str("FASTPANEL_MOUNT_PATH", "/__fastpanel")
    )
    store_max_requests: int = field(
        default_factory=lambda: _env_int("FASTPANEL_STORE_MAX_REQUESTS", 100)
    )
    show_sql: bool = field(
        default_factory=lambda: _env_bool("FASTPANEL_SHOW_SQL", True)
    )
    show_logging: bool = field(
        default_factory=lambda: _env_bool("FASTPANEL_SHOW_LOGGING", True)
    )
    show_cache: bool = field(
        default_factory=lambda: _env_bool("FASTPANEL_SHOW_CACHE", True)
    )
    slow_query_ms: float = field(
        default_factory=lambda: _env_float("FASTPANEL_SLOW_QUERY_MS", 100.0)
    )
    # Panel class lists — typed as Any to avoid importing the panel module here,
    # which would create circular imports at load time.
    panels: list[Any] | None = None
    extra_panels: list[Any] = field(default_factory=list)
    excluded_paths: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Normalise values and apply derived defaults after construction."""
        # The mount path itself must always be excluded so the internal API
        # endpoints never get instrumented by the middleware.
        if self.mount_path not in self.excluded_paths:
            self.excluded_paths.append(self.mount_path)

        # Strip trailing slashes from mount_path for consistency.
        self.mount_path = self.mount_path.rstrip("/")

    @classmethod
    def from_kwargs(cls, **kwargs: Any) -> FastPanelConfig:
        """Construct a ``FastPanelConfig`` from arbitrary keyword arguments.

        Unknown keys are silently ignored, which makes this safe to call with
        a merged dict of user-supplied settings and defaults.

        Args:
            **kwargs: Any subset of ``FastPanelConfig`` field names.

        Returns:
            A new ``FastPanelConfig`` instance.
        """
        valid_fields = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        filtered = {k: v for k, v in kwargs.items() if k in valid_fields}
        return cls(**filtered)
