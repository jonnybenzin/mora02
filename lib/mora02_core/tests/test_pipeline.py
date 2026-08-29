import json

import pytest

from mora02_core.pipeline import (
    gate_decision_label,
    PipelineError,
    PipelineResult,
    resume_pipeline,
    run_pipeline,
)
from mora02_core.pipeline.lobster import _parse_envelope, _to_result
from mora02_core.pipeline.spec import compile_to_lobster, plan_rerun, resolve_wiring

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


# --- wiring: the implicit edges a spec leaves out -------------------------------
# These lock in the two rules that are easy to break: a gate does not interrupt
# the stdin chain, and a review hands the chain to its generated send sub-step.

_REVIEW_SPEC = {
    "name": "wiring-fixture",
    "steps": [
        {"llm.image_prompt": {"id": "p", "subject": "x"}},
        {"image.generate": {"id": "img"}},
        {"review": "ok?"},
        {"video.generate": {"id": "vid", "mode": "i2v"}},
    ],
}

_GATE_SPEC = {
    "name": "gate-fixture",
    "steps": [
        {"llm.complete": {"id": "a", "prompt": "x"}},
        {"gate": "go on?"},
        {"llm.complete": {"id": "b"}},
    ],
}


def _wiring(spec):
    return {w.step_id: w for w in resolve_wiring(spec)}


def test_gate_is_transparent_for_the_stdin_chain():
    w = _wiring(_GATE_SPEC)
    # b reads from a, NOT from the gate -- but it does wait on the gate.
    assert w["b"].source == "a"
    assert w["b"].gate == "gate"
    assert w["gate"].source is None


def test_review_hands_the_chain_to_its_send_sub_step():
    w = _wiring(_REVIEW_SPEC)
    assert w["review_send"].source == "img"
    assert w["vid"].source == "review_send"
    assert w["vid"].gate == "review"


def test_explicit_in_and_fan_in_beat_the_default():
    spec = {
        "name": "explicit",
        "steps": [
            {"llm.complete": {"id": "s", "in": "none", "prompt": "x"}},
            {"llm.image_prompt": {"id": "p1", "in": "s"}},
            {"llm.image_prompt": {"id": "p2", "in": "s"}},
            {"image.generate": {"id": "i1", "in": "p1"}},
            {"image.generate": {"id": "i2", "in": "p2"}},
            {"gif.create": {"id": "g", "in": ["i1", "i2"]}},
        ],
    }
    w = _wiring(spec)
    assert w["s"].source is None            # in: "none" -- a pure producer
    assert w["p2"].source == "s"            # not p1, which is what the default would give
    assert w["g"].collect == ["i1", "i2"]   # order comes from the list, not from timing
    assert w["g"].depends_on == {"i1", "i2"}


def test_wiring_matches_what_the_compiler_emits():
    # The compiler must use the same edges -- that is the point of the extraction.
    for spec in (_GATE_SPEC, _REVIEW_SPEC):
        w = _wiring(spec)
        for step in compile_to_lobster(spec)["steps"]:
            expected = w[step["id"]].source
            actual = step.get("stdin", "").removeprefix("$").removesuffix(".stdout") or None
            assert actual == expected, step["id"]


# --- selective re-run: what a change makes stale ---------------------------------


def test_rerun_only_touches_what_depends_on_the_change():
    plan = plan_rerun(_REVIEW_SPEC, ["img"])
    # The video hangs off the image through the review's send sub-step.
    assert plan.redo == ["img", "review_send", "review", "vid"]
    assert plan.reuse == ["p"]


def test_rerun_of_a_late_step_leaves_everything_before_it_alone():
    plan = plan_rerun(_REVIEW_SPEC, ["vid"])
    assert plan.redo == ["vid"]
    assert plan.reuse == ["p", "img", "review_send", "review"]
    # The approval still stands, but the partial run has to supply it.
    assert plan.gates_needed == ["review"]


def test_a_new_subject_invalidates_the_approval_of_the_old_one():
    # The human approved THAT image. Regenerate it and the decision is worthless,
    # so the gate must be asked again rather than replayed.
    plan = plan_rerun(_REVIEW_SPEC, ["img"])
    assert "review" in plan.redo
    assert plan.gates_needed == []


def test_parallel_branches_do_not_drag_each_other_in():
    spec = {
        "name": "branches",
        "steps": [
            {"llm.complete": {"id": "s", "in": "none", "prompt": "x"}},
            {"llm.image_prompt": {"id": "p1", "in": "s"}},
            {"llm.image_prompt": {"id": "p2", "in": "s"}},
            {"image.generate": {"id": "i1", "in": "p1"}},
            {"image.generate": {"id": "i2", "in": "p2"}},
            {"gif.create": {"id": "g", "in": ["i1", "i2"]}},
        ],
    }
    plan = plan_rerun(spec, ["p1"])
    assert plan.redo == ["p1", "i1", "g"]      # the gif collects i1, so it follows
    assert "p2" in plan.reuse and "i2" in plan.reuse


# --- gate decisions: one flat answer, whichever shape the gate used -------------


def test_gate_decision_label_covers_both_gate_shapes():
    # approval: gate -> a bool
    assert gate_decision_label(approve=True) == "approve"
    assert gate_decision_label(approve=False) == "reject"
    # input: gate (what a review sends back) -> a dict
    assert gate_decision_label(response={"approved": True}) == "approve"
    assert gate_decision_label(response={"approved": False}) == "reject"
    # cancel wins over everything
    assert gate_decision_label(approve=True, cancel=True) == "cancel"
    # a plain structured answer that is not an approval at all
    assert gate_decision_label(response={"colour": "red"}) == "response"


# --- partial re-run: replay the unchanged, re-ask nothing already decided --------


def _kinds(steps):
    out = {}
    for st in steps:
        if "input" in st:
            out[st["id"]] = "gate"
        elif "/pipeline/replay" in st.get("run", ""):
            out[st["id"]] = "replay"
        else:
            out[st["id"]] = "run"
    return out


def test_partial_run_replays_the_unchanged_steps():
    plan = plan_rerun(_REVIEW_SPEC, ["vid"])
    steps = compile_to_lobster(
        _REVIEW_SPEC, run_id="new", reuse=plan.reuse, reuse_from="old"
    )["steps"]
    assert _kinds(steps) == {
        "p": "replay", "img": "replay", "review_send": "replay", "vid": "run"
    }


def test_a_reused_gate_is_dropped_and_its_condition_with_it():
    # The human approved in the earlier run; asking again would be the bug.
    plan = plan_rerun(_REVIEW_SPEC, ["vid"])
    steps = compile_to_lobster(
        _REVIEW_SPEC, run_id="new", reuse=plan.reuse, reuse_from="old"
    )["steps"]
    assert "review" not in [st["id"] for st in steps]
    vid = next(st for st in steps if st["id"] == "vid")
    assert "condition" not in vid


def test_a_replayed_step_still_obeys_a_gate_that_is_asked_again():
    # Change the image and the approval is worthless, so the gate runs. Steps
    # that ARE reused must not sneak past a fresh "no".
    plan = plan_rerun(_REVIEW_SPEC, ["img"])
    steps = compile_to_lobster(
        _REVIEW_SPEC, run_id="new", reuse=plan.reuse, reuse_from="old"
    )["steps"]
    assert _kinds(steps)["review"] == "gate"
    assert _kinds(steps)["p"] == "replay"


def test_overrides_reach_both_the_command_and_the_wiring():
    steps = compile_to_lobster(
        _REVIEW_SPEC, overrides={"img": {"flow": "nanban"}}
    )["steps"]
    img = next(st for st in steps if st["id"] == "img")
    assert "flow=nanban" in img["run"]


def test_reuse_without_a_source_run_is_refused():
    with pytest.raises(PipelineError, match="reuse_from"):
        compile_to_lobster(_REVIEW_SPEC, reuse=["p"])


# --- gate answers are outputs too ----------------------------------------------
# A gate publishes what the human answered into the run bucket under its own id,
# so feedback reaches a later step through the ordinary reference mechanism
# instead of a construct of its own.

_FEEDBACK_SPEC = {
    "name": "feedback-fixture",
    "steps": [
        {"llm.image_prompt": {"id": "p", "subject": "x"}},
        {"image.generate": {"id": "img"}},
        {"review": "ok?"},
        {"image.edit": {"id": "fix", "in": "review_send",
                        "prompt": {"from": "review.feedback"}}},
    ],
}


def test_a_step_may_pull_one_field_out_of_a_gate_answer():
    step = next(
        s for s in compile_to_lobster(_FEEDBACK_SPEC)["steps"] if s["id"] == "fix"
    )
    assert "__ref_prompt=review.feedback" in step["run"]


def test_a_dotted_ref_depends_on_the_step_not_the_field():
    w = _wiring(_FEEDBACK_SPEC)
    assert "review" in w["fix"].depends_on
    # ...so changing the answer makes the step that consumes it stale
    assert plan_rerun(_FEEDBACK_SPEC, ["review"]).redo == ["review_send", "review", "fix"]


def test_a_ref_to_an_unknown_step_is_still_refused_when_dotted():
    spec = {
        "name": "bad-ref",
        "steps": [{"llm.complete": {"id": "a", "prompt": {"from": "nope.field"}}}],
    }
    with pytest.raises(PipelineError, match="unknown or later"):
        compile_to_lobster(spec)
