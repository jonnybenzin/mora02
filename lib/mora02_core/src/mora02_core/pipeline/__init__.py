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
from pathlib import Path
from typing import Any, Union

from mora02_core.pipeline._errors import PipelineError
from mora02_core.pipeline.base import PipelineResult, PipelineRunner
from mora02_core.pipeline.lobster import LobsterRunner
from mora02_core.pipeline.registry import get_runner, register_runner
from mora02_core.pipeline import runbucket, runlog, vocab
from mora02_core.pipeline.spec import (
    GateStep,
    OpStep,
    PipelineSpec,
    ReviewStep,
    compile_to_lobster,
    load_spec,
)

# Where run_pipeline_spec writes the compiled .lobster. Must be a path the
# OpenClaw gateway container also sees (lobster runs there via docker exec) —
# mount /opt/mora02/volumes/openclaw/workspace at this path in both containers.
_DEFAULT_WORKSPACE = "/data/openclaw/workspace"

__all__ = [
    "run_pipeline",
    "resume_pipeline",
    "run_pipeline_sync",
    "resume_pipeline_sync",
    "run_pipeline_spec",
    "run_pipeline_spec_sync",
    "compile_to_lobster",
    "load_spec",
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
) -> PipelineResult:
    """Resume a paused workflow with the external decision.

    Pass exactly one of: ``response`` (structured input for an ``input:`` gate),
    ``approve`` (yes/no for an ``approval:`` gate), or ``cancel=True``.
    """
    return await get_runner(runner).resume(
        token, response=response, approve=approve, cancel=cancel
    )


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
) -> PipelineResult:
    """Blocking wrapper around :func:`resume_pipeline` for sync callers."""
    return asyncio.run(
        resume_pipeline(
            token, response=response, approve=approve, cancel=cancel, runner=runner
        )
    )


async def run_pipeline_spec(
    spec: Union[PipelineSpec, dict, str, Path],
    *,
    args: dict[str, Any] | None = None,
    runner: str | None = None,
    workspace: str | None = None,
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
        spec_hash=spec_hash,
        args=args,
        runner=runner or os.environ.get("MORA02_PIPELINE_RUNNER", "lobster"),
        steps=len(lobster.get("steps", [])),
        lobster_path=path,
    )
    res = await run_pipeline(path, args=args, runner=runner)
    runlog.log_event(
        run_id, "run_result",
        status=res.status, ok=res.ok, is_paused=res.is_paused,
        resume_token=res.resume_token,
    )
    return res


def run_pipeline_spec_sync(
    spec: Union[PipelineSpec, dict, str, Path],
    *,
    args: dict[str, Any] | None = None,
    runner: str | None = None,
    workspace: str | None = None,
) -> PipelineResult:
    """Blocking wrapper around :func:`run_pipeline_spec` for sync callers."""
    return asyncio.run(
        run_pipeline_spec(spec, args=args, runner=runner, workspace=workspace)
    )
