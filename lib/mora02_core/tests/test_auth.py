import pytest

from mora02_core import auth


def test_require_returns_value(monkeypatch):
    monkeypatch.setenv("MORA02_TEST_VAR", "hello")
    assert auth.require("MORA02_TEST_VAR") == "hello"


def test_require_missing_raises(monkeypatch):
    monkeypatch.delenv("MORA02_TEST_MISSING", raising=False)
    with pytest.raises(RuntimeError, match="required by mora02_core"):
        auth.require("MORA02_TEST_MISSING")


def test_require_empty_string_raises(monkeypatch):
    monkeypatch.setenv("MORA02_TEST_EMPTY", "")
    with pytest.raises(RuntimeError):
        auth.require("MORA02_TEST_EMPTY")


def test_get_returns_default_when_unset(monkeypatch):
    monkeypatch.delenv("MORA02_DEFINITELY_NOT_SET_XYZ", raising=False)
    assert auth.get("MORA02_DEFINITELY_NOT_SET_XYZ", "fallback") == "fallback"


def test_get_returns_value_when_set(monkeypatch):
    monkeypatch.setenv("MORA02_TEST_GET", "value")
    assert auth.get("MORA02_TEST_GET", "fallback") == "value"
