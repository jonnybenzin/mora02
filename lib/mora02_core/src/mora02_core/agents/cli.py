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
from typing import Callable

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


def first_json_object(out: str, accept: Callable[[dict], bool] | None = None) -> dict | None:
    """Pull the answer object out of CLI output that may carry other noise.

    Slicing from the first brace to the last breaks as soon as the CLI prints a
    warning afterwards (measured in phase 0: "Detected unsettled top-level
    await" follows the JSON), or the answer text itself contains braces.

    ``accept`` says which object is the answer. The default is the shape of
    `agent` and `models list` -- an object carrying ``result`` or ``models``.
    A config subtree has no fixed key; deploy.py passes its own test.
    """
    accept = accept or (lambda o: "result" in o or "models" in o)
    decoder = json.JSONDecoder()
    for i, ch in enumerate(out):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(out[i:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and accept(obj):
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

    data = first_json_object(out)
    if data is None:
        raise AgentError(f"unreadable answer from openclaw: {out[:300]}")

    result = data.get("result") or {}
    payloads = result.get("payloads") or [{}]
    meta = result.get("meta") or {}
    agent_meta = meta.get("agentMeta") or {}
    # Why the turn ended. "stop" means it finished; anything else -- a length
    # cap, an abort -- means the answer you are holding is a fragment. Passing
    # only the text on makes a cut-off answer indistinguishable from a complete
    # one, which is the failure every house rule in this layer is written
    # against; it would be absurd to commit it in the transport.
    stop = meta.get("stopReason") or (meta.get("completion") or {}).get("stopReason")

    # What the turn actually DID, not what it said it did. An answer built from
    # three searches and eight pages and one built from a single search look
    # alike in prose; here they do not. This is the difference between asking
    # "why was that answer thin" and guessing at it -- and it is the only way to
    # tell a model that will not iterate from a method that never told it to.
    # An absent summary means no tool ran -- openclaw only reports the block
    # when there was something to report. Defaulting to 0 rather than None is
    # deliberate: "zero tool calls on a question that needed them" is the single
    # most useful thing this field can say, and leaving it null hides exactly
    # that case while showing all the harmless ones.
    # What the gateway thinks its context budget is, and how close this turn
    # came. Surfaced because that number was wrong by a factor of four --
    # contextWindow 128000 on a server running 32768 -- and nothing showed it:
    # the gateway reported "fits" while a turn overran and returned no answer.
    # A budget you cannot see is a budget nobody checks.
    budget = agent_meta.get("contextBudgetStatus") or {}

    # What the turn consumed. Zero on a local profile, real on a cloud one --
    # and worth carrying because a research turn makes many model calls, each
    # resending a growing history, so the bill is not obvious from the answer.
    # NOTE: openclaw reports the LAST call, not the sum over the turn. It is a
    # floor on the cost, never the whole of it, and it is labelled as such
    # rather than quietly presented as a total.
    usage = agent_meta.get("lastCallUsage") or {}

    summary = meta.get("toolSummary") or {}
    tools = summary.get("tools") or []
    calls = summary.get("calls", 0)
    return {
        "text": payloads[0].get("text") or "",
        "stop_reason": stop,
        "complete": stop in (None, "stop", "end_turn"),
        "agent": agent,
        "session_key": key,
        "session_id": agent_meta.get("sessionId"),
        "run_id": data.get("runId"),
        "status": data.get("status"),
        "duration_ms": meta.get("durationMs"),
        "ctx_budget": budget.get("contextTokenBudget"),
        "ctx_prompt": budget.get("estimatedPromptTokens"),
        "ctx_left": budget.get("remainingPromptBudgetTokens"),
        "ctx_route": budget.get("route"),
        "usage_in": usage.get("input"),
        "usage_out": usage.get("output"),
        "usage_cache_read": usage.get("cacheRead"),
        "usage_note": "last model call of the turn, not the sum",
        "tool_calls": calls,
        "tools_used": tools,
        "tool_failures": summary.get("failures", 0),
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


async def models() -> list[dict]:
    """The models the gateway can run an agent on, from ``models list --json``.

    The Pilot has its own model registry, but that one speaks Pilot keys
    ("qwen", "sonnet") and the gateway wants provider-prefixed ids
    ("llama-local/current", "anthropic/claude-sonnet-4-6"). Asking the gateway
    is the only way to offer exactly the ids it will accept.

    ``local`` is decided HERE by the provider prefix and not taken from the
    gateway's own field: measured 2026-09-02, the gateway reports
    ``"local": false`` for the llama-local provider, because "local" to it means
    a model running inside its own process. To this house, local means the
    weights are on this machine and the question never leaves it -- and that is
    the prefix. The same rule agents.py uses to decide which weights to report.
    """
    container = os.environ.get("MORA02_OPENCLAW_CONTAINER", _DEFAULT_CONTAINER)
    docker_bin = os.environ.get("MORA02_DOCKER_BIN", "docker")
    proc = await asyncio.create_subprocess_exec(
        docker_bin, "exec", container, "openclaw", "models", "list", "--json",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
    if proc.returncode != 0:
        raise AgentError(f"could not list models: {(stderr or b'').decode()[:300]}")
    data = first_json_object((stdout or b"").decode(errors="replace")) or {}
    out: list[dict] = []
    for m in data.get("models") or []:
        key = str(m.get("key") or "")
        if not key:
            continue
        out.append({
            "key": key,
            "name": m.get("name") or key,
            "context_window": m.get("contextWindow"),
            "local": key.startswith("llama-local/"),
            "available": bool(m.get("available", True)),
            "tags": m.get("tags") or [],
        })
    return out
