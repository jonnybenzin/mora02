"""HTTP surface for the agent layer.

Thin on purpose: the CLI bridge lives in ``mora02_core.agents`` so that Pilot,
a later rollout script and the tests can all reach an agent without going
through HTTP. What is left here is what only a web layer can do -- turn a
request into arguments, and an error into a status code.

The first router in this service. main.py has grown past three thousand lines
with every endpoint inline; the agent layer will bring instances, a rollout and
a builder, and starting it in its own module keeps that growth out of there.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from mcp_tools import begin_turn, notes_since, reviewed_this_turn, urls_since
from mora02_core import pricing
from mora02_core.agents import AgentError, ask, listing
from mora02_core._common import get_logger

log = get_logger("agents")

# Full paths rather than a prefix. The prefix form needed a route literally
# spelled "s" to produce /agents, which reads as a typo to anyone who has not
# been told; with a third route arriving it stops being worth the cleverness.
router = APIRouter(tags=["agents"])

# The roster as the repo holds it, seen through the mount. The gateway has its
# own idea of which agents exist (see /agents); this is the other half -- the
# label, icon and description a person needs, which the gateway never stores.
AGENTS_DIR = Path(os.environ.get("MORA02_AGENTS_DIR", "/data/agents"))

# How long a turn may take, when the caller does not say and the agent's own
# manifest does not either. The bridge's own default was set when a turn was a
# question and an answer; a research turn that searches, reads four pages, notes
# and reviews legitimately runs minutes, and cutting it off at three looks
# exactly like a broken agent. An agent that needs longer says so in its
# agent.json rather than everyone waiting for the slowest.
_DEFAULT_TURN_TIMEOUT = 180

# USD per million tokens, (input, output). Only the models openclaw's bundled
# catalogue actually offers here; a model not in this table simply reports no
# cost rather than a guessed one.
#
# Cache reads bill at a tenth of the input rate. They are the bulk of a research
# turn: measured, a turn's last call reported ONE input token and 3031 output —
# everything else had been read from cache. Pricing input alone therefore
# reports a cost roughly one order of magnitude too low, which is the kind of
# wrong number that gets believed because it is pleasant.
_CACHE_READ_SHARE = 0.10

_RATES = {
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-opus-4-6": (5.00, 25.00),
    "claude-opus-4-7": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
}


def _manifest(agent_id: str) -> dict:
    path = AGENTS_DIR / "instances" / agent_id / "agent.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def agent_timeout(agent_id: str) -> int:
    try:
        return int(_manifest(agent_id).get("timeout", _DEFAULT_TURN_TIMEOUT))
    except (ValueError, TypeError):
        return _DEFAULT_TURN_TIMEOUT


class AgentMessage(BaseModel):
    message: str
    # The Pilot conversation this turn belongs to. It becomes the OpenClaw
    # session key, so the same conversation keeps its thread across turns --
    # and across a rebuild of this container, because the mapping is computed
    # rather than remembered.
    conversation: str = "default"
    model: Optional[str] = None
    timeout: Optional[int] = None


@router.get("/agents")
async def get_agents():
    """List the agents the GATEWAY knows — the running truth, not the intent."""
    try:
        return {"agents": await listing()}
    except AgentError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/agents/roster")
async def get_roster():
    """The agents as people see them: label, icon, colour, description.

    Read by looking, exactly as the rollout does — one folder under
    ``instances/`` is one agent, and its folder name is its id. Nothing
    enumerates them, so an agent created in the builder appears here without
    anything else being edited. That is the whole of increment 3.

    Only ``active`` agents are returned. ``main`` is a letterbox rather than
    someone to talk to, and offering it in a chat would invite exactly the turn
    its narrow tool list exists to make harmless.
    """
    instances = AGENTS_DIR / "instances"
    if not instances.is_dir():
        # A 503 naming the mount rather than an empty list: "no agents" and
        # "the directory was never mounted" look identical to a UI, and only
        # one of them is something an operator can fix.
        raise HTTPException(
            status_code=503,
            detail=f"no agent instances at {instances} — is /opt/mora02/agents "
                   f"mounted into this container?",
        )

    agents = []
    for folder in sorted(instances.iterdir()):
        manifest = folder / "agent.json"
        if not folder.is_dir() or folder.name.startswith(".") or not manifest.is_file():
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue  # a broken manifest hides itself, never the others
        if not data.get("active", True):
            continue
        agents.append({
            "id": folder.name,
            "label": data.get("label") or folder.name,
            "icon": data.get("icon", ""),
            "colour": data.get("colour", ""),
            "description": data.get("description", ""),
            "skills": data.get("skills", []),
            "sort_order": data.get("sort_order", 100),
            # What a bare "/<agent>" should send. Empty for an agent that needs
            # a question; set for one whose first move is to ask one.
            "opening": data.get("opening", ""),
        })

    agents.sort(key=lambda a: (a["sort_order"], a["id"]))
    return {"agents": agents}


@router.post("/agent/{agent_id}/message")
async def post_agent_message(agent_id: str, req: AgentMessage):
    """Run one turn and return the answer.

    502 rather than 500 on an AgentError: the failure is in the gateway
    container behind us, and saying so distinguishes "the agent could not
    answer" from "this service is broken".
    """
    # How much a tool may hand back per call belongs to the agent, not to the
    # module: a limit cut for a 32k window forces a large-context model into
    # five calls where one would do, and every call is a round trip.
    limits = _manifest(agent_id).get("limits")
    started = begin_turn(limits if isinstance(limits, dict) else None)
    try:
        result = await ask(
            agent_id,
            req.message,
            conversation=req.conversation,
            model=req.model,
            timeout=req.timeout or agent_timeout(agent_id),
        )
    except AgentError as e:
        log.warning("agent %s failed: %s", agent_id, e)
        raise HTTPException(status_code=502, detail=str(e))

    # What the web tools really touched during this turn. Not decoration: a
    # citation that is not in `sources.read` was not read, and that is a fact
    # about the answer which the answer itself cannot be trusted to report.
    result["sources"] = urls_since(started)
    # The notes the agent took while reading. Held beside the answer on purpose:
    # a restriction that is in the notes and NOT in the answer is the failure
    # this whole stage exists to catch, and it is only visible if both are shown.
    notes = notes_since(started)
    result["notes"] = notes
    result["notes_with_limit"] = sum(1 for n in notes if n.get("restriction"))
    # Did it look at its own notes before composing? Notes taken and never
    # re-read is the measured failure one step on: the coffee-machine answer
    # named a different winner than its own note did.
    result["notes_reviewed"] = reviewed_this_turn()

    # Price the reported usage. A floor, not a total -- openclaw reports the
    # last model call of the turn, and a research turn makes many. Said out
    # loud in the field name rather than left for someone to discover on an
    # invoice.
    rate = _RATES.get((result.get("model") or "").lower())
    if rate and result.get("usage_in") is not None:
        usd = ((result["usage_in"] / 1e6) * rate[0]
               + ((result.get("usage_cache_read") or 0) / 1e6) * rate[0] * _CACHE_READ_SHARE
               + ((result.get("usage_out") or 0) / 1e6) * rate[1])
        result["cost_usd_last_call"] = round(usd, 4)
        result["cost_eur_last_call"] = round(pricing.to_eur(usd) or 0, 4)

    log.info(
        "agent %s answered in %sms with %s tool call(s) %s, read %s page(s) (session %s)",
        agent_id, result.get("duration_ms"), result.get("tool_calls"),
        result.get("tools_used"), result["sources"]["read_count"],
        result.get("session_key"),
    )
    if result["sources"]["read_count"] and not notes:
        # Not an error, but the exact shape of the failure that was measured:
        # pages read, nothing written down, restrictions lost on the way out.
        log.warning("agent %s read %s page(s) and took no notes",
                    agent_id, result["sources"]["read_count"])
    return result
