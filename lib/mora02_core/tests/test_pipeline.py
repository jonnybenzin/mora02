import json

import pytest

from mora02_core.pipeline import (
    PipelineError,
    PipelineResult,
    resume_pipeline,
    run_pipeline,
)
from mora02_core.pipeline.lobster import _parse_envelope, _to_result

# A real "needs_input" envelope captured from `lobster run --mode tool`.
_RUN_PAUSED = json.dumps(
    {
        "protocolVersion": 1,
        "ok": True,
        "status": "needs_input",
        "output": [],
        "requiresApproval": None,
        "requiresInput": {
            "type": "input_request",
            "prompt": "Approve to continue the pipeline?",
            "responseSchema": {"type": "object", "properties": {"approved": {"type": "boolean"}}},
            "subject": "Sent via Signal. Message ID: 1781332708085",
            "resumeToken": "eyJ0b2tlbiI6ICJhYmMifQ",  # gitleaks:allow - fixture, base64 of {"token": "abc"}
        },
    }
).encode()

_RESUME_OK = json.dumps(
    {"protocolVersion": 1, "ok": True, "status": "ok", "output": ["Sent via Signal."], "requiresApproval": None, "requiresInput": None}
).encode()

_RUNTIME_ERROR = json.dumps(
    {"protocolVersion": 1, "ok": False, "error": {"type": "runtime_error", "message": "command failed (127)"}}
).encode()


def test_parse_paused_run_lifts_resume_token():
    res = _to_result(_parse_envelope(_RUN_PAUSED))
    assert isinstance(res, PipelineResult)
    assert res.ok is True
    assert res.status == "needs_input"
    assert res.is_paused is True
    assert res.resume_token == "eyJ0b2tlbiI6ICJhYmMifQ"  # gitleaks:allow - same fixture as above
    assert res.requires_input["prompt"].startswith("Approve")


def test_parse_completed_resume():
    res = _to_result(_parse_envelope(_RESUME_OK))
    assert res.ok is True
    assert res.status == "ok"
    assert res.is_paused is False
    assert res.output == ["Sent via Signal."]


def test_runtime_error_is_a_result_not_a_raise():
    # A workflow that runs but fails comes back as ok=False, not an exception.
    res = _to_result(_parse_envelope(_RUNTIME_ERROR))
    assert res.ok is False
    assert res.error["type"] == "runtime_error"


def test_parse_garbage_returns_none():
    assert _parse_envelope(b"not json at all") is None


async def test_run_missing_docker_raises(monkeypatch):
    monkeypatch.setenv("MORA02_DOCKER_BIN", "/nonexistent/docker-xyz")
    with pytest.raises(PipelineError, match="docker"):
        await run_pipeline("/data/openclaw/workspace/x.lobster")


async def test_resume_without_decision_raises():
    with pytest.raises(PipelineError, match="decision"):
        await resume_pipeline("some-token")


async def test_unknown_runner_raises():
    with pytest.raises(PipelineError, match="unknown pipeline runner"):
        await run_pipeline("/x.lobster", runner="does-not-exist")
