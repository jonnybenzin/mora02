import pytest

from mora02_core.notify import NotifyError, NotifyResult, notify, notify_sync
from mora02_core.notify import openclaw as openclaw_mod


async def test_log_backend_returns_ok():
    res = await notify("signal", "+49123", "hello", backend="log")
    assert isinstance(res, NotifyResult)
    assert res.ok is True
    assert res.backend == "log"
    assert res.channel == "signal"
    assert res.target == "+49123"


def test_notify_sync_log_backend():
    res = notify_sync("signal", "+49123", "hello", backend="log")
    assert res.ok is True
    assert res.backend == "log"


async def test_unknown_backend_raises():
    with pytest.raises(NotifyError, match="unknown notify backend"):
        await notify("signal", "+49123", "hello", backend="does-not-exist")


async def test_openclaw_missing_docker(monkeypatch):
    # With no docker binary reachable, the openclaw backend fails clearly
    # rather than hanging or sending nowhere.
    monkeypatch.setenv("MORA02_DOCKER_BIN", "/nonexistent/docker-xyz")
    with pytest.raises(NotifyError, match="docker"):
        await notify("signal", "+49123", "hello", backend="openclaw")


class _FakeProc:
    """A gateway call that succeeds and reports an id, without a gateway."""

    returncode = 0

    async def communicate(self):
        return b'{"messageId": "fake-1"}', b""


def _record_calls(monkeypatch) -> list:
    calls: list = []

    async def fake_exec(*argv, **_kw):
        calls.append(list(argv))
        return _FakeProc()

    monkeypatch.setattr(openclaw_mod.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.delenv("MORA02_NOTIFY_MEDIA_CAPTION", raising=False)
    return calls


async def test_caption_travels_as_its_own_message(monkeypatch):
    """A caption cannot ride along with an image, so it follows as its own message.

    Measured against Signal on 29 August 2026: a caption sent with --media
    arrives as its first character only ("Pipeline-Testlauf …" -> "P"), and the
    --presentation field replaces it with a "<media:image>" placeholder. Both
    are upstream of this repository, so the adapter splits the send instead.
    """
    calls = _record_calls(monkeypatch)
    caption = "eine Bildunterschrift, die vollstaendig ankommen muss"

    await notify("signal", "+49123", caption, media="/x/y.png", backend="openclaw")

    assert len(calls) == 2, "an image with a caption must go as two sends"
    picture, words = calls
    assert "--media" in picture
    # The picture carries one invisible character, not nothing: with no message at
    # all the gateway writes a literal "<media:image>" under the image, and a plain
    # space is trimmed back to that. One character survives the truncation intact.
    assert picture[picture.index("--message") + 1] == "\u200b"
    assert "--message" in words and "--media" not in words
    assert words[words.index("--message") + 1] == caption


async def test_inline_mode_restores_the_single_send(monkeypatch):
    """The split is a switch, not a rewrite - for the day the gateway is fixed."""
    calls = _record_calls(monkeypatch)
    monkeypatch.setenv("MORA02_NOTIFY_MEDIA_CAPTION", "inline")

    await notify("signal", "+49123", "caption", media="/x/y.png", backend="openclaw")

    assert len(calls) == 1
    assert "--media" in calls[0] and "--message" in calls[0]


async def test_media_without_caption_stays_one_send(monkeypatch):
    calls = _record_calls(monkeypatch)
    await notify("signal", "+49123", "", media="/x/y.png", backend="openclaw")
    assert len(calls) == 1
    assert "--message" not in calls[0]


async def test_text_only_stays_one_send(monkeypatch):
    calls = _record_calls(monkeypatch)
    await notify("signal", "+49123", "nur Text", backend="openclaw")
    assert len(calls) == 1
    assert "--media" not in calls[0]
