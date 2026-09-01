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
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

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
    try:
        result = await ask(
            agent_id,
            req.message,
            conversation=req.conversation,
            model=req.model,
            timeout=req.timeout,
        )
    except AgentError as e:
        log.warning("agent %s failed: %s", agent_id, e)
        raise HTTPException(status_code=502, detail=str(e))

    log.info(
        "agent %s answered in %sms (session %s)",
        agent_id, result.get("duration_ms"), result.get("session_key"),
    )
    return result
