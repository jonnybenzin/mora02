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

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from mora02_core.agents import AgentError, ask, listing
from mora02_core._common import get_logger

log = get_logger("agents")

router = APIRouter(prefix="/agent", tags=["agents"])


class AgentMessage(BaseModel):
    message: str
    # The Pilot conversation this turn belongs to. It becomes the OpenClaw
    # session key, so the same conversation keeps its thread across turns --
    # and across a rebuild of this container, because the mapping is computed
    # rather than remembered.
    conversation: str = "default"
    model: Optional[str] = None
    timeout: Optional[int] = None


@router.get("s")          # GET /agents
async def get_agents():
    """List the agents the gateway knows."""
    try:
        return {"agents": await listing()}
    except AgentError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/{agent_id}/message")
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
