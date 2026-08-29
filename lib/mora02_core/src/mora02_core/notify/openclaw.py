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

An image WITH a caption goes as two invocations - picture first, words second -
because a caption sent alongside media arrives truncated to its first character.
See ``send`` for the measurement and for the switch back.

Config (env):
  MORA02_OPENCLAW_CONTAINER  gateway container name, default ``mora02-openclaw``
  MORA02_DOCKER_BIN          docker binary, default ``docker``
  MORA02_NOTIFY_MEDIA_CAPTION  ``separate`` (default) or ``inline``
"""

from __future__ import annotations

import asyncio
import json
import os

from mora02_core.notify._errors import NotifyError
from mora02_core.notify.base import NotifyResult

_DEFAULT_CONTAINER = "mora02-openclaw"

# The picture's own caption when the words travel separately - see send(). Written
# as an escape rather than as the character itself: an invisible literal in source
# is the kind of thing a later tidy-up deletes without anyone noticing it was load
# bearing.
_INVISIBLE = "\u200b"  # zero-width space


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
        media: str | None = None,
    ) -> NotifyResult:
        container, docker_bin = self._resolve()

        # Channels render plain text, so title and link travel inline in the body.
        # `openclaw message send` makes --message optional once --media is set, so
        # an image can travel with or without a caption. The media path/URL must be
        # reachable from *inside* the gateway container (a mounted dir or a URL it
        # can fetch).
        body = _compose(message, title=title, link=link)
        if not body and not media:
            raise NotifyError("notify needs a message or media to send")

        # A caption cannot travel WITH an image through this gateway. Measured on
        # 29 August 2026 against Signal: with --media, "Pipeline-Testlauf …"
        # arrived as "P" and "ZZZ-ANFANG mitte ENDE-ZZZ" as "Z" - a string being
        # indexed at [0] somewhere upstream, reproducible and independent of
        # punctuation. The other field, --presentation, replaces the text with a
        # literal "<media:image>" placeholder. Both are outside this repository.
        #
        # So an image with a caption goes as TWO messages: the picture, then the
        # words. Two notifications instead of one is the price; a caption that
        # silently loses everything but its first letter is not a price worth
        # paying. Set MORA02_NOTIFY_MEDIA_CAPTION=inline to go back to one send
        # once the gateway carries captions properly - the behaviour is a switch,
        # not a rewrite.
        caption_mode = os.environ.get("MORA02_NOTIFY_MEDIA_CAPTION", "separate")
        split = bool(media and body and caption_mode != "inline")

        if split:
            # A zero-width space as the picture's own caption. Sent with no message
            # at all, the gateway writes a literal "<media:image>" under the image.
            # Sent with one, it keeps the first character - so the caption has to
            # be exactly one character wide and invisible. A plain space does not
            # work: whitespace is trimmed and the placeholder comes back (measured
            # 29 August 2026). U+200B is not whitespace to a trimmer and not ink to
            # a reader.
            result = await self._send_once(channel, target, body=_INVISIBLE, media=media)
            try:
                await self._send_once(channel, target, body=body)
            except NotifyError as e:
                # The picture is already delivered, so say precisely what is
                # missing rather than reporting a failed send.
                raise NotifyError(
                    f"media delivered, but its caption could not follow: {e}"
                ) from e
            return result

        return await self._send_once(channel, target, body=body or None, media=media)

    async def _send_once(
        self,
        channel: str,
        target: str,
        *,
        body: str | None = None,
        media: str | None = None,
    ) -> NotifyResult:
        """One ``openclaw message send`` invocation inside the gateway container."""
        container, docker_bin = self._resolve()
        argv = [
            docker_bin, "exec", container,
            "openclaw", "message", "send",
            "--channel", channel,
            "--target", target,
        ]
        if body:
            argv += ["--message", body]
        if media:
            argv += ["--media", media]
        argv.append("--json")

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
