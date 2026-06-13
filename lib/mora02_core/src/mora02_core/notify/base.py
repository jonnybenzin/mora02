"""Notify adapter contract: NotifyResult + NotifyAdapter protocol."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class NotifyResult:
    """Outcome of a successful delivery.

    Returned by ``notify``/``notify_sync`` on success; failures raise
    ``NotifyError`` instead, so the result always describes a delivered message.
    ``message_id`` is the backend's id when it exposes one (None otherwise).
    """

    ok: bool
    channel: str
    target: str
    backend: str
    message_id: str | None = None


class NotifyAdapter(Protocol):
    """A delivery backend.

    The default is ``OpenClawAdapter``; ``LogAdapter`` is the dev/test stub.
    An implementation sends exactly one message and returns a ``NotifyResult``,
    or raises ``NotifyError`` on failure. Adapters must be cheap to construct
    (resolve config lazily in ``send``) so they can be registered as singletons.
    """

    name: str

    async def send(
        self,
        channel: str,
        target: str,
        message: str,
        *,
        title: str | None = None,
        link: str | None = None,
    ) -> NotifyResult: ...
