"""Talk to an OpenClaw agent through the gateway container's CLI.

Why CLI-exec and not the gateway's RPC: the same reason as
``mora02_core.notify.openclaw`` -- the gateway grants the RPC only to paired
devices, while the CLI inside the container is already authorised. Phase 0 of
the agent layer measured that script-runner reaches it through the mounted
docker socket (ADR-020), the same path that already carries
``lobster run|resume`` and ``openclaw message send``.

Environment:
  MORA02_OPENCLAW_CONTAINER  gateway container, default ``mora02-openclaw``
  MORA02_DOCKER_BIN          docker binary, default ``docker``
  MORA02_AGENT_TIMEOUT       seconds per turn, default 180
"""

from __future__ import annotations

import asyncio
import json
import os
import re

_DEFAULT_CONTAINER = "mora02-openclaw"
_DEFAULT_TIMEOUT = 180

# openclaw session keys are "agent:<id>:<key>"; keep our half to characters
# that survive a shell, a JSON field and a file name unchanged.
_SAFE = re.compile(r"[^A-Za-z0-9_.-]")


class AgentError(RuntimeError):
    """The turn did not happen, or did not come back in a usable shape."""


def session_key(agent: str, conversation: str) -> str:
    """Map a Pilot conversation onto an OpenClaw session, deterministically.

    A pure function rather than a dictionary in memory: the same Pilot session
    resolves to the same OpenClaw session after a container restart, so the
    thread survives a redeploy. The alternative -- a lookup table in the
    process -- loses every conversation whenever script-runner is rebuilt,
    which happens on any python change.
    """
    return f"agent:{_SAFE.sub('-', agent)}:{_SAFE.sub('-', conversation)[:64]}"


def _first_json_object(out: str) -> dict | None:
    """Pull the result object out of output that may carry other noise.

    Slicing from the first brace to the last breaks as soon as the CLI prints a
    warning afterwards, or the answer text itself contains braces.
    """
    decoder = json.JSONDecoder()
    for i, ch in enumerate(out):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(out[i:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "result" in obj:
            return obj
    return None


async def ask(
    agent: str,
    message: str,
    *,
    conversation: str,
    model: str | None = None,
    timeout: int | None = None,
) -> dict:
    """Run one agent turn and return what it said.

    Never passes ``--deliver``: the reply belongs to whoever asked, and a turn
    that also posts itself to Signal would surprise the caller. Never passes
    ``--local`` either -- the turn runs through the gateway, so it uses the
    configured provider rather than whatever keys happen to be in the shell.
    """
    if not message.strip():
        raise AgentError("an agent turn needs a message")

    container = os.environ.get("MORA02_OPENCLAW_CONTAINER", _DEFAULT_CONTAINER)
    docker_bin = os.environ.get("MORA02_DOCKER_BIN", "docker")
    seconds = timeout or int(os.environ.get("MORA02_AGENT_TIMEOUT", _DEFAULT_TIMEOUT))
    key = session_key(agent, conversation)

    argv = [
        docker_bin, "exec", container,
        "openclaw", "agent",
        "--agent", agent,
        "--session-key", key,
        "--message", message,
        "--json",
        "--timeout", str(seconds),
    ]
    if model:
        argv += ["--model", model]

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=seconds + 30
        )
    except FileNotFoundError as e:
        raise AgentError(
            f"docker binary {docker_bin!r} not found - this container needs the "
            "docker CLI and a mounted docker socket to reach the gateway"
        ) from e
    except asyncio.TimeoutError as e:
        # Killing our client leaves the exec'd process running inside the
        # container, where it keeps talking to the model. Take it with us.
        await _kill_inside(docker_bin, container, key)
        raise AgentError(f"agent {agent!r} did not answer within {seconds}s") from e

    out = (stdout or b"").decode(errors="replace") + (stderr or b"").decode(errors="replace")
    if proc.returncode != 0:
        raise AgentError(f"openclaw agent failed: {out.strip()[:400]}")

    data = _first_json_object(out)
    if data is None:
        raise AgentError(f"unreadable answer from openclaw: {out[:300]}")

    result = data.get("result") or {}
    payloads = result.get("payloads") or [{}]
    meta = result.get("meta") or {}
    agent_meta = meta.get("agentMeta") or {}
    return {
        "text": payloads[0].get("text") or "",
        "agent": agent,
        "session_key": key,
        "session_id": agent_meta.get("sessionId"),
        "run_id": data.get("runId"),
        "status": data.get("status"),
        "duration_ms": meta.get("durationMs"),
        # Which weights actually answered is NOT this field: the provider name
        # points at a port, and a local profile swap leaves it unchanged.
        "provider": agent_meta.get("provider"),
        "model": agent_meta.get("model"),
    }


async def _kill_inside(docker_bin: str, container: str, key: str) -> None:
    """Best effort: end the turn we abandoned, so it stops using the GPU."""
    try:
        proc = await asyncio.create_subprocess_exec(
            docker_bin, "exec", container, "sh", "-c", f"pkill -f '{key}' || true",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.communicate(), timeout=20)
    except Exception:
        pass


async def listing() -> list[dict]:
    """The agents the gateway knows, as name + workspace."""
    container = os.environ.get("MORA02_OPENCLAW_CONTAINER", _DEFAULT_CONTAINER)
    docker_bin = os.environ.get("MORA02_DOCKER_BIN", "docker")
    proc = await asyncio.create_subprocess_exec(
        docker_bin, "exec", container, "openclaw", "agents", "list",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
    if proc.returncode != 0:
        raise AgentError(f"could not list agents: {(stderr or b'').decode()[:300]}")

    agents: list[dict] = []
    for line in (stdout or b"").decode(errors="replace").splitlines():
        line = line.rstrip()
        if line.startswith("- "):
            name = line[2:].split(" ")[0].strip()
            agents.append({"id": name, "default": "(default)" in line})
        elif agents and line.strip().startswith("Workspace:"):
            agents[-1]["workspace"] = line.split(":", 1)[1].strip()
        elif agents and line.strip().startswith("Model:"):
            agents[-1]["model"] = line.split(":", 1)[1].strip()
    return agents
