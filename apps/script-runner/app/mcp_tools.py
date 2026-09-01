"""The three verbs an agent may use on the pipeline layer, spoken as MCP.

Increment 2 of the agent layer gives the agent hands. This is the hand, and
what it CANNOT hold is the point of it.

Why not the built-in tools. The ``lobster`` tool inside OpenClaw cannot hold an
``input:`` gate at all, and an agent turn resolves its own ``approval:`` gates
(see ``mora02_core.pipeline.lobster``) -- so handing it over would dissolve HITL
from the inside. ``exec`` is worse: the tool bench measured five models reaching
for five different tools to force a gate, and a shell was the commonest. MCP is
the only path that adds exactly one capability and nothing else.

So this server offers ``flows_list``, ``flow_run`` and ``run_status`` -- and no
resume, no approve, no cancel. Pillar 6 of the plan ("the agent does not release
a gate") stops being a request to the model and becomes a property of its tool
surface. ``flow_run`` therefore also DROPS the ``resume_token`` that
``/pipeline/run-spec`` hands back: whoever holds that token can open the gate,
so it must not travel into a model's context.

THE HANDSHAKE, as measured on 2026-09-01 against openclaw 2026.6.1 (2e08f0f);
the full capture is ``notizen/phase0-agenten/mcp-handshake-260901-1018.log``::

    POST initialize                 protocolVersion "2025-11-25",
                                    clientInfo "openclaw-bundle-mcp"
    POST notifications/initialized  -> 202, no body
    GET  /mcp                       -> 405 is accepted; it wants an SSE stream
                                       and carries on without one
    POST tools/list
    POST tools/call
    DELETE /mcp                     -> 200

It sends ``accept: application/json, text/event-stream``, so a plain JSON
response is enough -- no SSE, no session manager. It re-initialises on EVERY
turn rather than reusing a session. Our ``Mcp-Session-Id`` is echoed back on
later requests once we have offered it.

That measurement is why this is ~200 lines of stdlib-shaped code instead of the
MCP SDK: the SDK's argument is that it maintains protocol details, and the
protocol in play is four methods and one response shape, all of them observed.
``tests/agents/test_mcp_handshake.py`` replays the capture, so an OpenClaw
update that starts asking for something else fails loudly here rather than
silently taking the agent's hands away.

Registered on the gateway side by ``scripts/agents-deploy.py`` as::

    openclaw mcp add mora02 --url http://script-runner:8096/mcp \\
        --transport streamable-http

MIND THE BLAST RADIUS: an MCP server is registered GLOBALLY. Measured on
2026-09-01, a server projected with ``codex.agents: ["researcher"]`` still
reached ``main``. The working guard is an explicit ``agents.list[].tools.allow``
per agent -- an agent WITHOUT one gets every tool there is. The rollout
therefore writes an allowlist for every agent, ``main`` included.

Like the rest of script-runner this carries no authentication; the port is
published on 127.0.0.1 only and the network is mora02-net. That is the standing
posture of this service, not a decision taken here.
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
from fastapi import APIRouter, Request, Response

from mora02_core._common import get_logger
from mora02_core.pipeline import (
    PipelineError,
    run_pipeline_spec,
    runlog as pipeline_runlog,
)

log = get_logger("mcp")

router = APIRouter(tags=["mcp"])

# Where named specs live -- the same directory /pipeline/flows reads, so the
# agent picks from exactly the library a human sees in the Pilot.
_SPECS_DIR = os.environ.get("MORA02_PIPELINE_SPECS_DIR", "/data/pipelines/specs")
_PILOT_URL = os.environ.get("PILOT_URL", "http://pilot:8098")

_SERVER_NAME = "mora02-pipelines"
_SERVER_VERSION = "1.0.0"

# Offered on every response. The client picks it up after initialize and sends
# it back; nothing depends on it, but omitting it entirely is a difference from
# the capture, and this is not the place to be creative.
_SESSION_ID = "mora02-pipelines"


# ---------------------------------------------------------------------------
# The tools
# ---------------------------------------------------------------------------
# Every description names its TRIGGER, not just its subject. Phase 0's most
# expensive finding: only the description reaches the prompt, and one that does
# not say WHEN to reach for the tool is never reached for -- with no error and
# no trace. A badly worded description here is a silent outage.

TOOLS: list[dict[str, Any]] = [
    {
        "name": "flows_list",
        "description": (
            "Use this whenever you need to know which pipelines exist, or before "
            "starting one, to find its exact name. Returns every saved flow with "
            "its name, description and step count. Takes no arguments."
        ),
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "flow_run",
        "description": (
            "Use this to actually START a pipeline once you know its name from "
            "flows_list. Returns a run_id and a status. A flow may PAUSE at a gate "
            "that only a human can open: when it does, the status says so and the "
            "decision is placed in the human's inbox automatically. You cannot "
            "open a gate yourself and there is no tool for it -- report that the "
            "run is waiting and stop."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "flow": {
                    "type": "string",
                    "description": "The flow's name, exactly as flows_list gives it.",
                },
                "args": {
                    "type": "object",
                    "description": "Input values for the run, as a JSON object. Omit if the flow needs none.",
                },
            },
            "required": ["flow"],
        },
    },
    {
        "name": "run_status",
        "description": (
            "Use this to check how a run is doing after flow_run gave you a "
            "run_id, or when someone asks what happened to a run. Returns each "
            "step with its status, and whether the run finished, failed or is "
            "still waiting at a gate."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "The run_id from flow_run."},
            },
            "required": ["run_id"],
        },
    },
]


async def _flows_list() -> dict:
    flows = []
    try:
        names = sorted(os.listdir(_SPECS_DIR))
    except OSError:
        names = []
    for fname in names:
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(_SPECS_DIR, fname), encoding="utf-8") as fh:
                spec = json.load(fh)
        except (OSError, ValueError):
            continue  # a broken spec hides itself, it must not hide the others
        flows.append({
            "name": spec.get("name") or fname[:-5],
            "description": spec.get("description", ""),
            "steps": len(spec.get("steps", [])),
            "tags": spec.get("tags", []),
        })
    return {"flows": flows, "count": len(flows)}


async def _flow_run(flow: str, args: dict | None) -> dict:
    """Start a named flow and report where it got to -- without the gate key."""
    base = os.path.join(_SPECS_DIR, os.path.basename(flow))
    target = next(
        (p for p in (base, base + ".json", base + ".yaml", base + ".yml")
         if os.path.isfile(p)),
        None,
    )
    if target is None:
        # Naming what DOES exist turns a dead end into a next step, and costs a
        # model far less than guessing at another name.
        known = [f["name"] for f in (await _flows_list())["flows"]]
        return {
            "error": f"no flow named {flow!r}",
            "known_flows": known,
        }

    try:
        res = await run_pipeline_spec(target, args=args or None)
    except PipelineError as e:
        return {"error": f"the flow did not start: {e}"}

    run_id = getattr(res, "run_id", None)
    paused = bool(res.is_paused)
    out = {
        "run_id": run_id,
        "status": res.status,
        "ok": res.ok,
        "finished": not paused,
        "error": res.error,
    }

    if paused:
        # The token is deliberately absent from `out`. It is the gate key, and a
        # key in a model's context is a key the model can be talked into using.
        out["waiting_for_human"] = (
            "approval" if res.requires_approval else "input" if res.requires_input else "a decision"
        )
        out["note"] = (
            "This run is paused at a gate. The decision has been placed in the "
            "human's inbox. You cannot open it; say that it is waiting."
        )
        await _refile_gate(res, flow)
    else:
        out["output"] = res.output

    log.info("agent started flow %s -> run %s (paused=%s)", flow, run_id, paused)
    return out


async def _refile_gate(res, flow: str) -> None:
    """Put the pending decision in front of the human.

    Without this the run pauses and nobody learns of it: the Pilot files its own
    inbox item only for runs IT started, and this one was started by an agent.
    A failure here is reported into the answer rather than swallowed -- a gate
    nobody can see is worse than a flow that did not start.
    """
    payload = {
        "ok": res.ok,
        "status": res.status,
        "is_paused": True,
        "resume_token": res.resume_token,
        "output": res.output,
        "requires_input": res.requires_input,
        "requires_approval": res.requires_approval,
        "error": res.error,
        "runner": res.runner,
        "run_id": getattr(res, "run_id", None),
        # inbox_refile titles the item from this; without it every agent-started
        # gate would show up as the word "Pipeline".
        "pipeline": flow,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            await c.post(f"{_PILOT_URL}/inbox/refile", json=payload)
    except Exception:
        log.exception("could not file the gate for run %s into the inbox",
                      getattr(res, "run_id", None))
        raise


async def _run_status(run_id: str) -> dict:
    events = pipeline_runlog.read_events(os.path.basename(run_id))
    if not events:
        return {"error": f"no run named {run_id!r}"}
    start = next((e for e in events if e.get("kind") == "run_start"), {})
    result = next((e for e in reversed(events) if e.get("kind") == "run_result"), None)
    steps = [
        {"step": e.get("step_id"), "op": e.get("op"), "status": e.get("status"),
         "error": e.get("error")}
        for e in events if e.get("kind") == "step"
    ]
    return {
        "run_id": run_id,
        "pipeline": start.get("pipeline"),
        "started": start.get("ts"),
        "steps": steps,
        "steps_done": len(steps),
        "failed": any(s["status"] == "failed" for s in steps),
        "result": result.get("status") if result else "still running or waiting at a gate",
    }


async def _call(name: str, arguments: dict) -> dict:
    if name == "flows_list":
        return await _flows_list()
    if name == "flow_run":
        flow = arguments.get("flow")
        if not isinstance(flow, str) or not flow.strip():
            return {"error": "flow_run needs a 'flow' name"}
        args = arguments.get("args")
        return await _flow_run(flow.strip(), args if isinstance(args, dict) else None)
    if name == "run_status":
        rid = arguments.get("run_id")
        if not isinstance(rid, str) or not rid.strip():
            return {"error": "run_status needs a 'run_id'"}
        return await _run_status(rid.strip())
    return {"error": f"no such tool: {name}"}


# ---------------------------------------------------------------------------
# The protocol
# ---------------------------------------------------------------------------

async def _dispatch(msg: dict) -> dict | None:
    """One JSON-RPC message in, one response out. None means "notification"."""
    method = msg.get("method")
    mid = msg.get("id")

    if method == "initialize":
        # Echo the version the client asked for. Insisting on our own is the
        # commonest way a handshake fails, and we support no feature that
        # depends on which revision it is.
        asked = (msg.get("params") or {}).get("protocolVersion") or "2025-11-25"
        return {
            "jsonrpc": "2.0", "id": mid,
            "result": {
                "protocolVersion": asked,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": _SERVER_NAME, "version": _SERVER_VERSION},
            },
        }

    if isinstance(method, str) and method.startswith("notifications/"):
        return None

    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}

    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        args = params.get("arguments")
        result = await _call(name, args if isinstance(args, dict) else {})
        # An MCP tool error belongs in isError, not in a JSON-RPC error: the
        # latter reads to the model as "the tool is broken" rather than "the
        # thing you asked for is not there", and the difference decides whether
        # it retries sensibly or invents an answer.
        return {
            "jsonrpc": "2.0", "id": mid,
            "result": {
                "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                "isError": bool(result.get("error")),
            },
        }

    # Say what we did not understand rather than going quiet: if a later
    # OpenClaw needs a method we lack, this line is what tells us which.
    log.warning("unhandled mcp method: %s", method)
    return {
        "jsonrpc": "2.0", "id": mid,
        "error": {"code": -32601, "message": f"method not found: {method}"},
    }


def _headers() -> dict:
    return {"Mcp-Session-Id": _SESSION_ID}


@router.post("/mcp")
async def mcp_post(request: Request):
    try:
        msg = await request.json()
    except Exception:
        return Response(
            content=json.dumps({"jsonrpc": "2.0", "id": None,
                                "error": {"code": -32700, "message": "parse error"}}),
            status_code=400, media_type="application/json", headers=_headers(),
        )

    if isinstance(msg, list):
        out = [r for r in [await _dispatch(m) for m in msg] if r is not None]
        body = out or None
    else:
        body = await _dispatch(msg if isinstance(msg, dict) else {})

    # A notification gets 202 and no body. Measured: the client sends
    # notifications/initialized and then waits, so getting this wrong hangs the
    # handshake rather than failing it.
    if body is None:
        return Response(status_code=202, headers=_headers())
    return Response(
        content=json.dumps(body, ensure_ascii=False),
        media_type="application/json", headers=_headers(),
    )


@router.get("/mcp")
async def mcp_get():
    """No server-initiated stream on offer.

    The client asks for one with `accept: text/event-stream` and was measured to
    carry on unaffected when told no -- which is the spec's intent, and the
    reason this server needs no session manager.
    """
    return Response(
        content=json.dumps({"error": "no sse stream"}),
        status_code=405, media_type="application/json", headers=_headers(),
    )


@router.delete("/mcp")
async def mcp_delete():
    """The client closes its session here. We hold none, so this is a courtesy."""
    return Response(content="{}", media_type="application/json", headers=_headers())
