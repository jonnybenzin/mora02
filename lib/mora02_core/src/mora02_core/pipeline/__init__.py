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
from typing import Any

from mora02_core.pipeline._errors import PipelineError
from mora02_core.pipeline.base import PipelineResult, PipelineRunner
from mora02_core.pipeline.lobster import LobsterRunner
from mora02_core.pipeline.registry import get_runner, register_runner

__all__ = [
    "run_pipeline",
    "resume_pipeline",
    "run_pipeline_sync",
    "resume_pipeline_sync",
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
