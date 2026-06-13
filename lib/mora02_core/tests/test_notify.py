import pytest

from mora02_core.notify import NotifyError, NotifyResult, notify, notify_sync


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
