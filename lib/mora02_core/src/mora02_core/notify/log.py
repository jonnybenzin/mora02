"""LogAdapter — logs instead of delivering.

Selected via ``MORA02_NOTIFY_BACKEND=log``. Useful in tests and local dev when
no OpenClaw gateway is reachable: it never delivers and never raises.
"""

from __future__ import annotations

from mora02_core._common import get_logger
from mora02_core.notify.base import NotifyResult

_log = get_logger("mora02_core.notify.log")


class LogAdapter:
    """Writes the notification to the logger and reports success."""

    name = "log"

    async def send(
        self,
        channel: str,
        target: str,
        message: str,
        *,
        title: str | None = None,
        link: str | None = None,
        media: str | None = None,
    ) -> NotifyResult:
        _log.info(
            "[notify:log] channel=%s target=%s title=%r link=%r media=%r message=%r",
            channel,
            target,
            title,
            link,
            media,
            message,
        )
        return NotifyResult(ok=True, channel=channel, target=target, backend=self.name)
