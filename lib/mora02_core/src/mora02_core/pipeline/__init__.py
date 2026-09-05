"""mora02_core.pipeline — run & resume HITL workflows via a swappable runner.

The HITL mechanic for the native pipeline layer (ADR-022 / Nordstern). One call,
deterministic, no LLM in the loop:

    from mora02_core.pipeline import run_pipeline, resume_pipeline

    res = await run_pipeline("/data/openclaw/workspace/skill.lobster")
    if res.is_paused:                       # status == "needs_input"
        token = res.resume_token            # show res.requires_input in Pilot inbox
        # ...human approves in Pilot...
        res = await resume_pipeline(token, response={"approved": True})

The default runner is the headless Lobster CLI (``MORA02_PIPELINE_RUNNER=lobster``)
invoked via docker exec inside the gateway container. Scope is run/resume only —
the inbox UI and decision flow live in Pilot. Sync wrappers exist for non-async
callers (scripts, ActivePieces).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Union

from mora02_core.pipeline._errors import PipelineError
from mora02_core.pipeline.base import PipelineResult, PipelineRunner
from mora02_core.pipeline.lobster import LobsterRunner
from mora02_core.pipeline.registry import get_runner, register_runner
from mora02_core.pipeline import runbucket, runlog, vocab
from mora02_core._common import get_logger
from mora02_core.notify import NotifyError, notify
from mora02_core.pipeline.spec import (
    GateStep,
    OpStep,
    PipelineSpec,
    ReviewStep,
    compile_to_lobster,
    resolve_wiring,
    plan_rerun,
    RerunPlan,
    StepWiring,
    load_spec,
    spec_to_dict,
)

# Where run_pipeline_spec writes the compiled .lobster. Must be a path the
# OpenClaw gateway container also sees (lobster runs there via docker exec) —
# mount /opt/mora02/volumes/openclaw/workspace at this path in both containers.
_DEFAULT_WORKSPACE = "/data/openclaw/workspace"

__all__ = [
    "run_pipeline",
    "resume_pipeline",
    "gate_decision_label",
    "run_pipeline_sync",
    "resume_pipeline_sync",
    "run_pipeline_spec",
    "run_pipeline_spec_sync",
    "compile_to_lobster",
    "resolve_wiring",
    "plan_rerun",
    "RerunPlan",
    "StepWiring",
    "load_spec",
    "spec_to_dict",
    "rerun_pipeline_spec",
    "vocab",
    "runlog",
    "PipelineSpec",
    "OpStep",
    "GateStep",
    "ReviewStep",
    "PipelineError",
    "PipelineResult",
    "PipelineRunner",
    "LobsterRunner",
    "register_runner",
    "get_runner",
]


_log = get_logger("mora02_core.pipeline")


async def run_pipeline(
    pipeline_path: str,
    *,
    args: dict[str, Any] | None = None,
    runner: str | None = None,
) -> PipelineResult:
    """Start a workflow file. Returns a ``PipelineResult`` (may be paused at a gate).

    Raises ``PipelineError`` only on a transport failure (runner unreachable /
    unparseable output); a workflow runtime error comes back as ``ok=False``.
    ``runner`` overrides ``MORA02_PIPELINE_RUNNER`` for this call.
    """
    return await get_runner(runner).run(pipeline_path, args=args)


async def resume_pipeline(
    token: str,
    *,
    response: dict[str, Any] | None = None,
    approve: bool | None = None,
    cancel: bool = False,
    runner: str | None = None,
    run_id: str | None = None,
) -> PipelineResult:
    """Resume a paused workflow with the external decision.

    Pass exactly one of: ``response`` (structured input for an ``input:`` gate),
    ``approve`` (yes/no for an ``approval:`` gate), or ``cancel=True``.

    With ``run_id`` the decision is written to the run log as a ``gate_decision``
    event. Without it the resume still works, it just leaves no trace — the run
    log then shows a flow that mysteriously continues. Gates are reached in spec
    order, so the ORDER of these events in the log identifies which gate each
    decision belongs to; the resume token carries no gate id.
    """
    res = await get_runner(runner).resume(
        token, response=response, approve=approve, cancel=cancel
    )
    res.run_id = run_id
    # Publish the answer BEFORE logging it: the gate is identified by counting the
    # decisions already in the log, so an entry written first would shift the count.
    _publish_gate_answer(run_id, response=response, approve=approve, cancel=cancel)
    runlog.log_event(
        run_id, "gate_decision",
        decision=gate_decision_label(response=response, approve=approve, cancel=cancel),
        response=response,
        status=res.status, ok=res.ok, is_paused=res.is_paused,
    )
    # The resumed tail ran to its end (or to the next gate) inside this call, so
    # this is the run's fate now. Without it the last run_result in the log
    # stayed the pause from the initial call, and every reader that takes the
    # newest one - the Runs view, pipelog - showed a finished flow as waiting.
    runlog.log_event(
        run_id, "run_result",
        status=res.status, ok=res.ok, is_paused=res.is_paused,
        resume_token=res.resume_token, after="resume",
    )
    await report_run_failure(run_id, res)
    return res


def _publish_gate_answer(
    run_id: str | None,
    *,
    response: dict[str, Any] | None,
    approve: bool | None,
    cancel: bool,
) -> None:
    """Put a human's answer into the run bucket, under the gate it answered.

    This is what makes feedback usable INSIDE a run: a later step can pull the
    text a human wrote into a param with the ordinary ``{"from": "<gate>"}``
    reference from :mod:`runbucket`, or ``{"from": "<gate>.feedback"}`` for a
    single field. No new language construct is involved — a gate simply becomes
    a step with an output, like every other.

    Which gate is being answered is derived, not carried: the resume token names
    none. Gates are reached in spec order, so the number of decisions already in
    the log gives the position. In a partial re-run the reused gates never fire,
    so they are removed from the sequence first.

    Best-effort like the rest of the bucket: a run whose spec was not recorded,
    or a decision that arrives after the last gate, leaves no entry rather than
    breaking a resume that has otherwise already succeeded.
    """
    if not run_id:
        return
    try:
        events = runlog.read_events(run_id)
        start = next((e for e in events if e.get("kind") == "run_start"), None)
        if start is None or not start.get("spec"):
            return
        reused = set(start.get("reused") or ())
        gate_ids = [
            st.id
            for st in load_spec(start["spec"]).steps
            if isinstance(st, (GateStep, ReviewStep)) and st.id not in reused
        ]
        answered = sum(1 for e in events if e.get("kind") == "gate_decision")
        if answered >= len(gate_ids):
            return
        gate_id = gate_ids[answered]

        answer: dict[str, Any] = dict(response or {})
        if approve is not None:
            answer.setdefault("approved", approve)
        if cancel:
            answer["cancelled"] = True
            answer.setdefault("approved", False)
        runbucket.put(run_id, gate_id, answer)
        # Each field also under "<gate>.<field>", so a ref can pick one directly
        # instead of handing a whole dict to a param that wants a string.
        for key, value in answer.items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                runbucket.put(run_id, f"{gate_id}.{key}", value)
    except Exception:  # noqa: BLE001 — never let bookkeeping break a resume
        _log.warning("could not publish the gate answer for run %s", run_id)


def gate_decision_label(
    *,
    response: dict[str, Any] | None = None,
    approve: bool | None = None,
    cancel: bool = False,
) -> str:
    """Name what a human decided, across the three shapes a gate answer arrives in.

    A partial re-run needs one flat answer — "was this approved?" — no matter
    whether the gate was an ``approval:`` (a bool) or an ``input:`` gate (a dict
    with ``approved`` in it, which is what a review sends back).
    """
    if cancel:
        return "cancel"
    if approve is not None:
        return "approve" if approve else "reject"
    if isinstance(response, dict) and "approved" in response:
        return "approve" if response["approved"] else "reject"
    return "response"


def run_pipeline_sync(
    pipeline_path: str,
    *,
    args: dict[str, Any] | None = None,
    runner: str | None = None,
) -> PipelineResult:
    """Blocking wrapper around :func:`run_pipeline` for sync callers.

    Must not be called from within a running event loop.
    """
    return asyncio.run(run_pipeline(pipeline_path, args=args, runner=runner))


def resume_pipeline_sync(
    token: str,
    *,
    response: dict[str, Any] | None = None,
    approve: bool | None = None,
    cancel: bool = False,
    runner: str | None = None,
    run_id: str | None = None,
) -> PipelineResult:
    """Blocking wrapper around :func:`resume_pipeline` for sync callers."""
    return asyncio.run(
        resume_pipeline(
            token, response=response, approve=approve, cancel=cancel,
            runner=runner, run_id=run_id,
        )
    )


# ---------------------------------------------------------------------------
# A failed run tells the person
# ---------------------------------------------------------------------------
# A run that fails writes its fate into the log and nowhere else; the Runs view
# shows it to whoever happens to look. The cheap half of "failure paths" (the
# graph feature, where a step's failure takes another branch) is this: when
# the fate is failure, say so where the person is. Configured, not assumed:
#
#   MORA02_RUN_FAILURE_NOTIFY   signal | email | (unset: no message)
#   MORA02_<CHANNEL>_TARGET     the recipient, as notify uses it
#
# Runs started with trigger "test" never notify: the suites fail runs on
# purpose, dozens per pass, and every one of those would reach a phone.

_FAILED_STATUSES = {"failed", "error"}


def _run_failed(res: PipelineResult) -> bool:
    return (not res.ok) or res.status in _FAILED_STATUSES


def _failure_lines(run_id: str) -> tuple[str, str, str]:
    """(pipeline name, trigger, one line about the failing step) from the run log."""
    events = runlog.read_events(run_id)
    start = next((e for e in events if e.get("kind") == "run_start"), {})
    failed = next((e for e in reversed(events)
                   if e.get("kind") == "step" and e.get("status") == "failed"), None)
    if failed:
        where = f"step {failed.get('step_id')!r} ({failed.get('op')}): {failed.get('error') or 'failed'}"
    else:
        where = "no step reported a failure - the runner stopped"
    return start.get("pipeline") or run_id, start.get("trigger") or "manual", where


async def report_run_failure(run_id: str | None, res: PipelineResult | None = None, *,
                             error: str | None = None) -> None:
    """Send the failure of a run to the configured channel, if any. Never raises.

    Called after every run_result that is a failure - the initial run, a
    re-run, a resume, and the detached resume in script-runner. What is sent
    is what a person needs to act: which flow, which run, which step, what it
    said. The act is recorded in the run log as ``notified``, so a message
    that never arrived can be told from one that was never sent.
    """
    if not run_id:
        return
    channel = (os.environ.get("MORA02_RUN_FAILURE_NOTIFY") or "").strip().lower()
    if not channel:
        return
    if res is not None and not _run_failed(res):
        return
    try:
        pipeline, trigger, where = _failure_lines(run_id)
        if trigger == "test":
            return
        target = os.environ.get(f"MORA02_{channel.upper()}_TARGET")
        if not target:
            _log.warning("run %s failed, but MORA02_%s_TARGET is not set - nobody told", run_id, channel.upper())
            runlog.log_event(run_id, "notified", channel=channel, ok=False,
                             error=f"MORA02_{channel.upper()}_TARGET is not set")
            return
        detail = error or (res.error if res is not None and isinstance(res.error, str) else None)
        message = (f"Flow '{pipeline}' failed.\nRun {run_id}\n{where}"
                   + (f"\n{detail}" if detail and detail not in where else ""))
        await notify(channel, target, message, title=f"mora02: flow '{pipeline}' failed")
        runlog.log_event(run_id, "notified", channel=channel, target=target, ok=True)
    except NotifyError as e:
        _log.warning("could not report the failure of run %s: %s", run_id, e)
        runlog.log_event(run_id, "notified", channel=channel, ok=False, error=str(e))
    except Exception as e:  # reporting a failure must not become one
        _log.exception("failure report for run %s raised", run_id)
        runlog.log_event(run_id, "notified", channel=channel, ok=False, error=f"{type(e).__name__}: {e}")


def _vocab_hash() -> str:
    """A short fingerprint of the vocabulary a run was compiled against.

    Name and status of every op, hashed: enough to tell that two runs saw
    different vocabularies (an op added, one promoted from planned to wired)
    without storing the whole table in every log.
    """
    body = "\n".join(sorted(f"{op.name}:{op.status}" for op in vocab.all_ops()))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]


def _provenance(trigger: str) -> dict[str, Any]:
    """What a run_start records about the world it ran in, beyond the spec."""
    import mora02_core  # the package is initialised by now; its version lives there
    return {
        "trigger": trigger,
        "core_version": getattr(mora02_core, "__version__", None),
        "vocab_hash": _vocab_hash(),
        "runner_version": os.environ.get("MORA02_RUNNER_VERSION") or None,
    }


async def run_pipeline_spec(
    spec: Union[PipelineSpec, dict, str, Path],
    *,
    args: dict[str, Any] | None = None,
    runner: str | None = None,
    workspace: str | None = None,
    trigger: str = "manual",
    batch: dict[str, Any] | None = None,
) -> PipelineResult:
    """Compile a mora02 pipeline spec to ``.lobster``, write it, and run it.

    The convenience layer over :func:`compile_to_lobster` + :func:`run_pipeline`:
    ``spec`` may be a :class:`PipelineSpec`, an in-memory dict (e.g. emitted by an
    authoring front-end), or a path to a ``.json``/``.yaml`` file. The compiled
    ``.lobster`` is written to ``workspace`` (default ``/data/openclaw/workspace``,
    overridable via ``MORA02_PIPELINE_WORKSPACE``) and LEFT in place so it can be
    inspected, diffed, or run by hand. Returns the same ``PipelineResult`` as
    :func:`run_pipeline` (may be paused at a gate).

    A ``run_id`` is generated and baked into the compiled steps so the step
    endpoint can correlate its per-step log lines; ``run_start`` / ``run_result``
    events are written via :mod:`runlog`. Logging never breaks the run.
    """
    loaded = load_spec(spec)
    run_id = runlog.new_run_id()
    # Seed the run's variable inputs into the run bucket under "args.<name>" so a
    # {"arg": "<name>"} param resolves the same way a {"from": "<step>"} ref does
    # (see spec._is_arg / runbucket). Done before the first step runs.
    for _k, _v in (args or {}).items():
        runbucket.put(run_id, "args." + _k, _v)
    lobster = compile_to_lobster(loaded, run_id=run_id)

    ws = workspace or os.environ.get("MORA02_PIPELINE_WORKSPACE", _DEFAULT_WORKSPACE)
    os.makedirs(ws, exist_ok=True)
    path = os.path.join(ws, f"{loaded.name}.lobster")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(lobster, fh, indent=2)

    spec_hash = hashlib.sha256(
        json.dumps(lobster, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:16]
    runlog.log_event(
        run_id, "run_start",
        pipeline=loaded.name,
        # The spec ITSELF, not just its name: a partial re-run has to plan against
        # what actually ran. A library file may have been edited since, and a flow
        # sent straight from the builder was never a file at all.
        spec=spec_to_dict(loaded),
        spec_hash=spec_hash,
        args=args,
        runner=runner or os.environ.get("MORA02_PIPELINE_RUNNER", "lobster"),
        steps=len(lobster.get("steps", [])),
        lobster_path=path,
        **_provenance(trigger),
        **({"batch": batch} if batch else {}),
    )
    res = await run_pipeline(path, args=args, runner=runner)
    res.run_id = run_id  # so a pause can be carried to the inbox and back
    runlog.log_event(
        run_id, "run_result",
        status=res.status, ok=res.ok, is_paused=res.is_paused,
        resume_token=res.resume_token,
    )
    await report_run_failure(run_id, res)
    return res


# ---------------------------------------------------------------------------
# One spec, many argument sets
# ---------------------------------------------------------------------------

def new_batch_id() -> str:
    """Sortable like a run id, and recognisable as not one."""
    return "batch_" + runlog.new_run_id()


async def run_pipeline_batch(
    spec: Union[PipelineSpec, dict, str, Path],
    arg_sets: list[dict[str, Any]],
    *,
    runner: str | None = None,
    workspace: str | None = None,
    trigger: str = "manual",
    batch_id: str | None = None,
    on_result=None,
) -> dict[str, Any]:
    """Run one spec once per argument set, in order, each as a run of its own.

    The recipe stays the same; the ingredients change. Ten subjects through
    the same clip flow used to be ten starts and ten waits. Each run here is
    an ordinary run with its own log, and every log says which batch it came
    from and where in it (``batch: {id, index, size}``), so the runs can be
    read as a group afterwards. Sequential on purpose: there is one GPU.

    A run that pauses at a gate is handed to ``on_result`` (the caller files
    it where a human will see it) and the batch goes on to the next set; the
    decisions are taken one by one, in the inbox. A run that fails does not
    stop the others - its failure is reported the way any failed run is - but
    is counted. Returns the summary: batch id, one line per run, the counts.
    """
    bid = batch_id or new_batch_id()
    size = len(arg_sets)
    runs: list[dict[str, Any]] = []
    for index, args in enumerate(arg_sets, 1):
        record: dict[str, Any] = {"index": index, "args": args}
        try:
            res = await run_pipeline_spec(
                spec, args=args or None, runner=runner, workspace=workspace, trigger=trigger,
                batch={"id": bid, "index": index, "size": size},
            )
            record.update(run_id=res.run_id, status=res.status, ok=res.ok,
                          is_paused=res.is_paused)
            if on_result is not None:
                try:
                    await on_result(res)
                except Exception as e:  # filing is the caller's concern, not the batch's
                    _log.warning("batch %s: on_result for run %s raised: %s", bid, res.run_id, e)
        except PipelineError as e:
            # A spec that does not compile fails every set the same way; say
            # so once per set rather than pretending the rest would differ.
            record.update(run_id=None, status="error", ok=False, is_paused=False, error=str(e))
        runs.append(record)
    return {
        "batch_id": bid,
        "size": size,
        "runs": runs,
        "ok": sum(1 for r in runs if r.get("ok") and not r.get("is_paused")),
        "paused": sum(1 for r in runs if r.get("is_paused")),
        "failed": sum(1 for r in runs if not r.get("ok")),
    }


async def rerun_pipeline_spec(
    spec: Union[PipelineSpec, dict, str, Path],
    *,
    source_run_id: str,
    changed: Iterable[str],
    overrides: dict[str, dict[str, Any]] | None = None,
    args: dict[str, Any] | None = None,
    runner: str | None = None,
    workspace: str | None = None,
    trigger: str = "manual",
) -> PipelineResult:
    """Re-run only what a change made stale, replaying the rest from an earlier run.

    ``spec`` may DIFFER from the one ``source_run_id`` ran — an extra edit step, a
    rewired input, a changed param — as long as the reused ids still match. That
    is what makes a revision possible without cycles in the pipeline language: a
    revision is a new partial run, not a loop.

    Approvals already given are honoured rather than asked again, but only when
    the earlier answer was "approve": a gate that was rejected or cancelled stops
    this call, because continuing past a "no" is exactly the mistake the gate
    exists to prevent.
    """
    loaded = load_spec(spec)
    plan = plan_rerun(loaded, changed)
    if plan.gates_needed:
        _guard_reused_gates(loaded, plan.gates_needed, source_run_id)

    run_id = runlog.new_run_id()
    for _k, _v in (args or {}).items():
        runbucket.put(run_id, "args." + _k, _v)
    lobster = compile_to_lobster(
        loaded, run_id=run_id, overrides=overrides,
        reuse=plan.reuse, reuse_from=source_run_id,
    )

    ws = workspace or os.environ.get("MORA02_PIPELINE_WORKSPACE", _DEFAULT_WORKSPACE)
    os.makedirs(ws, exist_ok=True)
    path = os.path.join(ws, f"{loaded.name}.lobster")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(lobster, fh, indent=2)

    runlog.log_event(
        run_id, "run_start",
        pipeline=loaded.name,
        spec=spec_to_dict(loaded),
        rerun_of=source_run_id,
        redone=plan.redo,
        reused=plan.reuse,
        overrides=overrides,
        args=args,
        runner=runner or os.environ.get("MORA02_PIPELINE_RUNNER", "lobster"),
        steps=len(lobster.get("steps", [])),
        lobster_path=path,
        **_provenance(trigger),
    )
    res = await run_pipeline(path, args=args, runner=runner)
    res.run_id = run_id
    runlog.log_event(
        run_id, "run_result",
        status=res.status, ok=res.ok, is_paused=res.is_paused,
        resume_token=res.resume_token,
    )
    await report_run_failure(run_id, res)
    return res


def _guard_reused_gates(
    loaded: PipelineSpec, gates_needed: list[str], source_run_id: str
) -> None:
    """Refuse to replay an approval that was never given.

    Gates are reached in spec order and decisions are logged in the order they
    were made, so the Nth decision answers the Nth gate — the resume token
    carries no gate id, and this pairing is the only link there is.
    """
    gate_ids = [
        st.id for st in loaded.steps if isinstance(st, (GateStep, ReviewStep))
    ]
    decisions = [
        e.get("decision")
        for e in runlog.read_events(source_run_id)
        if e.get("kind") == "gate_decision"
    ]
    answered = dict(zip(gate_ids, decisions))
    for gate in gates_needed:
        verdict = answered.get(gate)
        if verdict != "approve":
            raise PipelineError(
                f"cannot reuse gate {gate!r} from run {source_run_id}: "
                f"its decision was {verdict or 'never recorded'}, not an approval — "
                "re-run that gate instead of replaying it"
            )


def run_pipeline_spec_sync(
    spec: Union[PipelineSpec, dict, str, Path],
    *,
    args: dict[str, Any] | None = None,
    runner: str | None = None,
    workspace: str | None = None,
    trigger: str = "manual",
) -> PipelineResult:
    """Blocking wrapper around :func:`run_pipeline_spec` for sync callers."""
    return asyncio.run(
        run_pipeline_spec(spec, args=args, runner=runner, workspace=workspace,
                          trigger=trigger)
    )
