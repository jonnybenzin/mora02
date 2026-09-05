"""mora02_core.notify — outbound human notifications via swappable backends.

One call, any channel:

    from mora02_core.notify import notify, notify_sync

    await notify("signal", "+49...", "Build done — approve?", link=inbox_url)
    notify_sync("signal", "+49...", "Build done")   # from sync code

The default backend is the OpenClaw gateway (``MORA02_NOTIFY_BACKEND=openclaw``);
switch to ``log`` for tests/dev. Scope is delivery only — the HITL inbox and
decision flow live in Pilot, not here (ADR-022).
"""

from __future__ import annotations

import asyncio

from mora02_core.notify._errors import NotifyError
from mora02_core.notify.base import NotifyAdapter, NotifyResult
from mora02_core.notify.log import LogAdapter
from mora02_core.notify.openclaw import OpenClawAdapter
from mora02_core.notify.registry import get_adapter, register_adapter

__all__ = [
    "notify",
    "notify_sync",
    "NotifyError",
    "NotifyResult",
    "NotifyAdapter",
    "OpenClawAdapter",
    "LogAdapter",
    "register_adapter",
    "get_adapter",
]


async def notify(
    channel: str,
    target: str,
    message: str,
    *,
    title: str | None = None,
    link: str | None = None,
    media: str | None = None,
    backend: str | None = None,
) -> NotifyResult:
    """Deliver ``message`` to ``target`` over ``channel``. Async core.

    Returns a ``NotifyResult`` on success; raises ``NotifyError`` on failure.
    ``media`` attaches an image/audio/video/document (a path the backend can read
    or a URL it can fetch); with media set, ``message`` may be empty (caption-less).
    ``backend`` overrides ``MORA02_NOTIFY_BACKEND`` for this one call.
    """
    # One call, any channel: the chat channels ride the gateway, mail does not.
    # Choosing the backend by channel here keeps that fact out of every caller.
    if backend is None and channel == "email":
        backend = "email"
    adapter = get_adapter(backend)
    return await adapter.send(channel, target, message, title=title, link=link, media=media)


def notify_sync(
    channel: str,
    target: str,
    message: str,
    *,
    title: str | None = None,
    link: str | None = None,
    media: str | None = None,
    backend: str | None = None,
) -> NotifyResult:
    """Blocking wrapper around :func:`notify` for sync callers (scripts, ActivePieces).

    Must not be called from within a running event loop — use :func:`notify`
    there instead.
    """
    return asyncio.run(
        notify(channel, target, message, title=title, link=link, media=media, backend=backend)
    )
