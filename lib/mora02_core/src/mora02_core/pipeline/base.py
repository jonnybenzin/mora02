"""Pipeline runner contract: PipelineResult + PipelineRunner protocol.

A pipeline runner executes a typed, multi-step workflow that may *pause* at a
human-in-the-loop gate and later *resume*. Unlike notify (one shot, success or
raise), a run has three normal outcomes carried in ``PipelineResult.status``:

  - ``"ok"``           the workflow ran to completion
  - ``"needs_input"``  it paused at an ``input:`` gate; ``requires_input`` holds
                       the prompt + response schema + a ``resume_token``
  - ``"needs_approval"`` it paused at an ``approval:`` gate

The HITL contract (ADR-022): the runner pauses deterministically and hands back
a ``resume_token``; an *external* decider (Pilot inbox / a human) calls
``resume`` with that token. The running process never self-approves — that was
the whole point of moving off the autonomous-agent invocation path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(slots=True)
class PipelineResult:
    """Outcome of a run/resume call — a parsed runner envelope.

    ``ok`` is the runner-level success flag (False on a workflow runtime error,
    with ``error`` populated). ``status`` is the workflow state. ``requires_input``
    / ``requires_approval`` carry the gate payload when paused. ``resume_token`` is
    lifted out of whichever gate is active for convenience. ``raw`` keeps the full
    envelope so callers never lose detail.
    """

    ok: bool
    status: str
    runner: str
    output: list[str] = field(default_factory=list)
    requires_input: dict[str, Any] | None = None
    requires_approval: dict[str, Any] | None = None
    resume_token: str | None = None
    error: dict[str, Any] | None = None
    raw: dict[str, Any] | None = None
    # The run this result belongs to. The runner does not know it (it only sees a
    # workflow file and a resume token) — the layer that MINTED the id fills it in,
    # so a paused result can be carried to the inbox and back without losing which
    # run a human decision belongs to.
    run_id: str | None = None

    @property
    def is_paused(self) -> bool:
        """True when the workflow stopped at a gate awaiting an external decision."""
        return self.status in ("needs_input", "needs_approval")


class PipelineRunner(Protocol):
    """A workflow runner backend.

    The default is ``LobsterRunner`` (headless ``lobster`` CLI via docker exec).
    Implementations must be cheap to construct (resolve config lazily) so they can
    be registered as singletons. The forward-looking reason this is an adapter and
    not a hardcoded call: the Nordstern is a native mora02_core step runner that
    later slots in here without touching caller code.
    """

    name: str

    async def run(
        self,
        pipeline_path: str,
        *,
        args: dict[str, Any] | None = None,
    ) -> PipelineResult: ...

    async def resume(
        self,
        token: str,
        *,
        response: dict[str, Any] | None = None,
        approve: bool | None = None,
        cancel: bool = False,
    ) -> PipelineResult: ...
