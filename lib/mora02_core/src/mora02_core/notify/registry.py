"""Adapter registry + env-driven default selection.

``MORA02_NOTIFY_BACKEND`` picks the active adapter (default ``openclaw``).
``register_adapter`` lets later backends (ntfy, pushover, email) plug in
without touching caller code — the ADR-022 mitigation against OpenClaw being a
single point of failure for notifications.
"""

from __future__ import annotations

import os

from mora02_core.notify._errors import NotifyError
from mora02_core.notify.base import NotifyAdapter
from mora02_core.notify.email import EmailAdapter
from mora02_core.notify.log import LogAdapter
from mora02_core.notify.openclaw import OpenClawAdapter

_ADAPTERS: dict[str, NotifyAdapter] = {}


def register_adapter(adapter: NotifyAdapter) -> None:
    """Register (or replace) an adapter under its ``.name``."""
    _ADAPTERS[adapter.name] = adapter


def get_adapter(name: str | None = None) -> NotifyAdapter:
    """Return the named adapter, or the env default (``MORA02_NOTIFY_BACKEND``)."""
    key = name or os.environ.get("MORA02_NOTIFY_BACKEND", "openclaw")
    try:
        return _ADAPTERS[key]
    except KeyError:
        known = ", ".join(sorted(_ADAPTERS)) or "(none)"
        raise NotifyError(
            f"unknown notify backend {key!r}; registered: {known}"
        ) from None


# Built-in adapters. Both construct cheaply (config is resolved lazily on send),
# so registering instances at import time is safe even with no gateway running.
register_adapter(OpenClawAdapter())
register_adapter(LogAdapter())
register_adapter(EmailAdapter())
