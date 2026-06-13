"""OpenClawAdapter — deliver by invoking the OpenClaw CLI inside the gateway container.

Why CLI-exec and not the WebSocket RPC: the gateway only grants the
``operator.write`` scope to clients connecting over loopback from inside its own
container. A WS client in another container authenticates with the shared token
but is left read-only (this matches known OpenClaw operator-scope behaviour), so
``send`` is refused. The CLI, run *inside* mora02-openclaw, connects via loopback
and is fully trusted — so outbound sends are routed through
``openclaw message send`` there.

This keeps OpenClaw as the single channel gateway: the same call delivers to any
channel OpenClaw supports (Signal, Telegram, ...), selected by ``channel``.

Mechanism::

    docker exec <container> openclaw message send \
        --channel <c> --target <t> --message <m> --json

The calling container therefore needs the docker CLI and a mounted docker socket
(as script-runner already has, per ADR-020).

Config (env):
  MORA02_OPENCLAW_CONTAINER  gateway container name, default ``mora02-openclaw``
  MORA02_DOCKER_BIN          docker binary, default ``docker``
"""

from __future__ import annotations

import asyncio
import json
import os

from mora02_core.notify._errors import NotifyError
from mora02_core.notify.base import NotifyResult

_DEFAULT_CONTAINER = "mora02-openclaw"


class OpenClawAdapter:
    """Default backend: send via ``openclaw message send`` inside the gateway container."""

    name = "openclaw"

    def __init__(self, container: str | None = None, docker_bin: str | None = None) -> None:
        # Overrides only; env is resolved lazily in send() so a singleton
        # registered at import time still picks up env set later (and tests can
        # monkeypatch it).
        self._container_override = container
        self._docker_bin_override = docker_bin

    def _resolve(self) -> tuple[str, str]:
        container = self._container_override or os.environ.get(
            "MORA02_OPENCLAW_CONTAINER", _DEFAULT_CONTAINER
        )
        docker_bin = self._docker_bin_override or os.environ.get("MORA02_DOCKER_BIN", "docker")
        return container, docker_bin

    async def send(
        self,
        channel: str,
        target: str,
        message: str,
        *,
        title: str | None = None,
        link: str | None = None,
    ) -> NotifyResult:
        container, docker_bin = self._resolve()

        # Channels render plain text, so title and link travel inline in the body.
        body = _compose(message, title=title, link=link)
        argv = [
            docker_bin, "exec", container,
            "openclaw", "message", "send",
            "--channel", channel,
            "--target", target,
            "--message", body,
            "--json",
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
        except FileNotFoundError as e:
            raise NotifyError(
                f"docker binary {docker_bin!r} not found — the calling container "
                "needs the docker CLI and a mounted docker socket to reach the "
                "OpenClaw gateway container."
            ) from e
        except OSError as e:
            raise NotifyError(f"failed to exec docker: {e!r}") from e

        if proc.returncode != 0:
            detail = (stderr or stdout).decode("utf-8", "replace").strip()
            raise NotifyError(
                f"openclaw send failed (exit {proc.returncode}) for "
                f"channel={channel} target={target}: {detail[:400]}"
            )

        return NotifyResult(
            ok=True,
            channel=channel,
            target=target,
            backend=self.name,
            message_id=_extract_message_id(stdout),
        )


def _compose(message: str, *, title: str | None, link: str | None) -> str:
    """Flatten title/link into one plain-text body for channel delivery."""
    parts: list[str] = []
    if title:
        parts.append(title)
    parts.append(message)
    if link:
        parts.append(link)
    return "\n\n".join(parts)


def _extract_message_id(stdout: bytes) -> str | None:
    """Best-effort pull of a message id from ``--json`` CLI output; None if absent.

    The CLI decorates output with banner lines around the JSON object, so we
    isolate the blob from the first ``{`` to the last ``}``.
    """
    text = stdout.decode("utf-8", "replace")
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    mid = data.get("messageId") or data.get("id") or data.get("timestamp")
    return str(mid) if mid is not None else None
