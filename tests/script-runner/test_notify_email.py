#!/usr/bin/env python3
"""notify over e-mail: the mail is built right, sent off the loop, and a missing
configuration says which line of docker/.env is missing.

Offline: smtplib is replaced by a recorder, nothing leaves the machine.

    bash tests/script-runner/run-all.sh
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "lib" / "mora02_core" / "src"))
sys.path.insert(0, str(REPO / "apps" / "script-runner" / "app"))

_mp = types.ModuleType("python_multipart")
_mp.__version__ = "0.0.20"
_sub = types.ModuleType("python_multipart.multipart")
for _n in ("MultiPartParser", "QuerystringParser", "FormParser", "MultipartPart",
           "File", "Field"):
    setattr(_sub, _n, type(_n, (), {}))
_sub.parse_options_header = lambda *a, **k: (b"", {})
_mp.multipart = _sub
sys.modules.setdefault("python_multipart", _mp)
sys.modules.setdefault("python_multipart.multipart", _sub)

DATA = Path(tempfile.mkdtemp(prefix="sr-mail-"))
STORE = DATA / "comfyui"
STORE.mkdir(parents=True)
os.environ["MORA02_SCRIPT_RUNNER_DATA"] = str(DATA)
os.environ["MORA02_PIPELINE_LOG_DIR"] = str(DATA / "logs")
os.environ["MORA02_ASSET_STORE_COMFYUI"] = str(STORE)
for k in ("MORA02_SMTP_HOST", "MORA02_SMTP_USER", "MORA02_SMTP_PASSWORD", "MORA02_SMTP_FROM",
          "MORA02_EMAIL_TARGET", "MORA02_SIGNAL_TARGET"):
    os.environ.pop(k, None)

import steps  # noqa: E402
from mora02_core.notify import email as mail  # noqa: E402
from mora02_core.notify import get_adapter  # noqa: E402

# Importing the service loads docker/.env into the environment, so the
# variables this suite reasons about are cleared AFTER the import, not before.
for k in ("MORA02_SMTP_HOST", "MORA02_SMTP_USER", "MORA02_SMTP_PASSWORD", "MORA02_SMTP_FROM",
          "MORA02_EMAIL_TARGET", "MORA02_SIGNAL_TARGET"):
    os.environ.pop(k, None)

results: list[tuple[str, str, str]] = []


def record(ok: bool, subject: str, detail: str = "") -> None:
    results.append(("ok" if ok else "FAIL", subject, detail))


class _Recorder:
    """Stands in for smtplib.SMTP: remembers what would have gone out."""
    sent: list = []
    logins: list = []
    tls: int = 0

    def __init__(self, host, port, timeout=None):
        _Recorder.host = (host, port)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        _Recorder.tls += 1

    def login(self, user, password):
        _Recorder.logins.append((user, password))

    def send_message(self, msg):
        _Recorder.sent.append(msg)


def main_() -> int:
    record(get_adapter("email").name == "email", "the registry knows the e-mail backend")

    # --- unconfigured: the error names the missing line -----------------------
    try:
        asyncio.run(steps._step_notify(["hello"], {"channel": "email", "target": "a@b.example"}))
        record(False, "without SMTP settings the step fails", "it did not")
    except ValueError as e:
        record("MORA02_SMTP_HOST" in str(e), "without SMTP settings the step names the missing variable", str(e)[:70])
    try:
        asyncio.run(steps._step_notify(["hello"], {"channel": "email"}))
        record(False, "without a recipient the step fails", "it did not")
    except ValueError as e:
        record("MORA02_EMAIL_TARGET" in str(e), "without a recipient it names the channel's own target variable", str(e)[:70])

    # --- configured: the mail is built and handed to SMTP -----------------------
    os.environ.update({"MORA02_SMTP_HOST": "smtp.example", "MORA02_SMTP_PORT": "2525",
                       "MORA02_SMTP_USER": "bot@example", "MORA02_SMTP_PASSWORD": "pw",
                       "MORA02_EMAIL_TARGET": "me@example"})
    real_smtp = mail.smtplib.SMTP
    mail.smtplib.SMTP = _Recorder
    try:
        out = asyncio.run(steps._step_notify(
            ["first line of the news", "", "second paragraph"],
            {"channel": "email", "title": "Run finished", "link": "http://x/run/1"}))
        msg = _Recorder.sent[-1]
        record(out["out"] == "first line of the news\n\nsecond paragraph" and out["type"] == "text",
               "the text passes through unchanged")
        record(msg["To"] == "me@example" and msg["From"] == "bot@example" and msg["Subject"] == "Run finished",
               "recipient from MORA02_EMAIL_TARGET, sender from the login, subject from the title",
               f"{msg['To']} <- {msg['From']}: {msg['Subject']}")
        body = msg.get_content()
        record("second paragraph" in body and "http://x/run/1" in body,
               "paragraphs and the link are in the body")
        record(_Recorder.host == ("smtp.example", 2525) and _Recorder.tls == 1
               and _Recorder.logins == [("bot@example", "pw")],
               "host, port, STARTTLS and login come from the environment")

        # a picture on stdin becomes an attachment, and the ref passes through
        (STORE / "shot.png").write_bytes(b"\x89PNG\r\n\x1a\nnot really")
        out = asyncio.run(steps._step_notify(
            ["asset://comfyui/shot.png"], {"channel": "email", "message": "the picture"}))
        msg = _Recorder.sent[-1]
        parts = [p for p in msg.iter_attachments()]
        record(out["out"] == "asset://comfyui/shot.png" and out["type"] == "image",
               "an asset ref passes through with its type")
        record(len(parts) == 1 and parts[0].get_filename() == "shot.png"
               and parts[0].get_content_type() == "image/png",
               "and travels as an attachment in the same mail", str([p.get_filename() for p in parts]))
        record(msg["Subject"] == "the picture", "without a title the message's first line is the subject")

        # ?target= beats the environment; an explicit channel target stays per channel
        asyncio.run(steps._step_notify(["x"], {"channel": "email", "target": "other@example"}))
        record(_Recorder.sent[-1]["To"] == "other@example", "?target= wins over the environment")
    finally:
        mail.smtplib.SMTP = real_smtp

    # --- signal keeps its own variable ------------------------------------------
    try:
        asyncio.run(steps._step_notify(["x"], {}))
        record(False, "signal without a target fails", "it did not")
    except ValueError as e:
        record("MORA02_SIGNAL_TARGET" in str(e), "the default channel still asks for MORA02_SIGNAL_TARGET", str(e)[:60])

    width = max(len(s) for _, s, _ in results)
    failed = 0
    for verdict, subject, detail in results:
        failed += verdict == "FAIL"
        print(f"[ {verdict:^4} ] {subject.ljust(width)}  {detail}")
    print(f"\n{len(results) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main_())
