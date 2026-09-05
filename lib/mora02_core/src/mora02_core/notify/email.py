"""E-mail delivery over SMTP - the one notify channel that does not go through
the OpenClaw gateway.

The gateway carries chat channels (Signal, Telegram, ...). Mail is older and
simpler than any of them and needs no gateway: the standard library speaks
SMTP, and a mail with an attachment is what a run's picture or clip becomes
when the recipient is not on a chat. Configuration from the environment, read
at send time so the adapter is free to construct:

  MORA02_SMTP_HOST      the server (e.g. smtp.gmail.com)
  MORA02_SMTP_PORT      default 587
  MORA02_SMTP_USER      login; also the default sender
  MORA02_SMTP_PASSWORD  the password - for Gmail an app password, not the account's
  MORA02_SMTP_FROM      sender address, default MORA02_SMTP_USER
  MORA02_SMTP_SECURITY  starttls (default) | ssl | none
  MORA02_EMAIL_TARGET   default recipient, the way MORA02_SIGNAL_TARGET is for Signal

The values live in docker/.env like every other secret; nothing here knows
them by value.
"""

from __future__ import annotations

import asyncio
import mimetypes
import os
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

from mora02_core.notify._errors import NotifyError
from mora02_core.notify.base import NotifyResult

# A mail needs a subject; without a title the first line of the message is it,
# cut to a width the classic clients still show whole.
_SUBJECT_MAX = 78


def _subject(message: str, title: str | None) -> str:
    if title:
        return title.strip()
    first = next((ln.strip() for ln in (message or "").splitlines() if ln.strip()), "")
    if len(first) > _SUBJECT_MAX:
        first = first[: _SUBJECT_MAX - 1].rstrip() + "…"
    return first or "mora02 notification"


def build_message(
    *, sender: str, to: str, message: str, title: str | None = None,
    link: str | None = None, media: str | None = None,
) -> EmailMessage:
    """The mail as it will be sent - separate from sending so a test can read it."""
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = _subject(message, title)
    body = message or ""
    if link:
        body = f"{body}\n\n{link}" if body else link
    msg.set_content(body or "(no text)")
    if media:
        path = Path(media)
        if not path.is_file():
            raise NotifyError(f"email: attachment not found: {media}")
        ctype, _ = mimetypes.guess_type(path.name)
        maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
        msg.add_attachment(path.read_bytes(), maintype=maintype, subtype=subtype, filename=path.name)
    return msg


def _send_blocking(msg: EmailMessage) -> str | None:
    host = os.environ.get("MORA02_SMTP_HOST")
    if not host:
        raise NotifyError("email: MORA02_SMTP_HOST is not set (docker/.env)")
    port = int(os.environ.get("MORA02_SMTP_PORT", "587"))
    user = os.environ.get("MORA02_SMTP_USER")
    password = os.environ.get("MORA02_SMTP_PASSWORD")
    security = os.environ.get("MORA02_SMTP_SECURITY", "starttls").lower()
    try:
        if security == "ssl":
            client = smtplib.SMTP_SSL(host, port, timeout=30, context=ssl.create_default_context())
        else:
            client = smtplib.SMTP(host, port, timeout=30)
        with client:
            if security == "starttls":
                client.starttls(context=ssl.create_default_context())
            if user and password:
                client.login(user, password)
            client.send_message(msg)
    except (smtplib.SMTPException, OSError) as e:
        raise NotifyError(f"email: {type(e).__name__}: {e}") from e
    return msg["Message-ID"]


class EmailAdapter:
    """Deliver over SMTP. ``channel`` is accepted for the interface and ignored -
    an e-mail is an e-mail; ``target`` is the recipient address."""

    name = "email"

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
        if not target:
            raise NotifyError("email needs a recipient (target)")
        # The server first: without it nothing else matters, and it is the line
        # a fresh installation is most likely to be missing.
        if not os.environ.get("MORA02_SMTP_HOST"):
            raise NotifyError("email: MORA02_SMTP_HOST is not set (docker/.env)")
        sender = os.environ.get("MORA02_SMTP_FROM") or os.environ.get("MORA02_SMTP_USER")
        if not sender:
            raise NotifyError("email: MORA02_SMTP_FROM or MORA02_SMTP_USER must be set (docker/.env)")
        msg = build_message(sender=sender, to=target, message=message, title=title,
                            link=link, media=media)
        # smtplib blocks on the network; the caller sits on the event loop.
        message_id = await asyncio.to_thread(_send_blocking, msg)
        return NotifyResult(ok=True, channel="email", target=target, backend=self.name,
                            message_id=message_id)
