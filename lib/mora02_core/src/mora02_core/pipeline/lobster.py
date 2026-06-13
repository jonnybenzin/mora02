"""LobsterRunner — run/resume Lobster workflows headlessly via the gateway container.

Why CLI-exec (the same shape as ``notify``): the HITL gate only holds when the
pipeline is driven by the *headless* Lobster engine, NOT by an OpenClaw agent
turn — an autonomous agent resolves its own ``approval:`` gates (and the in-process
lobster *tool* can't do ``input:`` at all). So we call the standalone ``lobster``
CLI (``@clawdbot/lobster``) inside the gateway container, where it runs
deterministically with no model in the loop:

    docker exec <container> lobster run    --mode tool --file <path> [--args-json …]
    docker exec <container> lobster resume --mode tool --token <token> \
        ( --response-json <json> | --approve yes|no | --cancel )

``--mode tool`` makes the CLI print a single JSON envelope we can parse. The
caller (script-runner, which already holds the docker socket per ADR-020) relays
Pilot's run/resume calls here; Pilot itself stays socket-free.

Config (env):
  MORA02_OPENCLAW_CONTAINER  gateway container name, default ``mora02-openclaw``
  MORA02_DOCKER_BIN          docker binary, default ``docker``
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from mora02_core.pipeline._errors import PipelineError
from mora02_core.pipeline.base import PipelineResult

_DEFAULT_CONTAINER = "mora02-openclaw"


class LobsterRunner:
    """Default runner: headless ``lobster`` CLI inside the gateway container."""

    name = "lobster"

    def __init__(self, container: str | None = None, docker_bin: str | None = None) -> None:
        # Overrides only; env is resolved lazily so a singleton registered at
        # import time still picks up env set later (and tests can monkeypatch it).
        self._container_override = container
        self._docker_bin_override = docker_bin

    def _resolve(self) -> tuple[str, str]:
        container = self._container_override or os.environ.get(
            "MORA02_OPENCLAW_CONTAINER", _DEFAULT_CONTAINER
        )
        docker_bin = self._docker_bin_override or os.environ.get("MORA02_DOCKER_BIN", "docker")
        return container, docker_bin

    async def run(
        self,
        pipeline_path: str,
        *,
        args: dict[str, Any] | None = None,
    ) -> PipelineResult:
        argv = ["lobster", "run", "--mode", "tool", "--file", pipeline_path]
        if args is not None:
            argv += ["--args-json", json.dumps(args)]
        return await self._exec(argv)

    async def resume(
        self,
        token: str,
        *,
        response: dict[str, Any] | None = None,
        approve: bool | None = None,
        cancel: bool = False,
    ) -> PipelineResult:
        argv = ["lobster", "resume", "--mode", "tool", "--token", token]
        # Exactly one decision mode. Precedence: cancel > structured response > approve.
        if cancel:
            argv.append("--cancel")
        elif response is not None:
            argv += ["--response-json", json.dumps(response)]
        elif approve is not None:
            argv += ["--approve", "yes" if approve else "no"]
        else:
            raise PipelineError(
                "resume needs a decision: pass response=, approve=, or cancel=True"
            )
        return await self._exec(argv)

    async def _exec(self, lobster_argv: list[str]) -> PipelineResult:
        container, docker_bin = self._resolve()
        argv = [docker_bin, "exec", container, *lobster_argv]

        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
        except FileNotFoundError as e:
            raise PipelineError(
                f"docker binary {docker_bin!r} not found — the calling container "
                "needs the docker CLI and a mounted docker socket to reach the "
                "OpenClaw gateway container."
            ) from e
        except OSError as e:
            raise PipelineError(f"failed to exec docker: {e!r}") from e

        envelope = _parse_envelope(stdout)
        if envelope is None:
            # No parseable envelope = a transport/exec failure, not a workflow error.
            detail = (stderr or stdout).decode("utf-8", "replace").strip()
            raise PipelineError(
                f"lobster {lobster_argv[1]} produced no JSON envelope "
                f"(exit {proc.returncode}): {detail[:400]}"
            )
        return _to_result(envelope)


def _parse_envelope(stdout: bytes) -> dict[str, Any] | None:
    """Isolate and parse the ``--mode tool`` JSON envelope; None if absent."""
    text = stdout.decode("utf-8", "replace")
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _to_result(env: dict[str, Any]) -> PipelineResult:
    """Map a Lobster envelope onto a PipelineResult.

    A workflow runtime error comes back as ``ok=False`` with ``error`` populated —
    that is a *result*, not a raised exception (see PipelineError docstring).
    """
    requires_input = env.get("requiresInput")
    requires_approval = env.get("requiresApproval")
    ok = bool(env.get("ok", False))
    gate = requires_input or requires_approval or {}
    return PipelineResult(
        ok=ok,
        status=env.get("status") or ("ok" if ok else "error"),
        runner="lobster",
        output=list(env.get("output") or []),
        requires_input=requires_input,
        requires_approval=requires_approval,
        resume_token=gate.get("resumeToken") if isinstance(gate, dict) else None,
        error=env.get("error"),
        raw=env,
    )
