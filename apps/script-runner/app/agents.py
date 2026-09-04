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

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
import httpx
from pydantic import BaseModel

from mcp_tools import (begin_turn, checks_earlier, checks_since, end_turn,
                       notes_earlier,
                       notes_since, open_notes, reviewed_this_turn,
                       single_source_notes, turn_progress, urls_since)
from mora02_core import auth, pricing
from mora02_core.agents import AgentError, ask, listing, session_key
from mora02_core.agents import models as gateway_models
from mora02_core.agents import deploy as deploy_mod
from mora02_core.agents.store import (StoreError, builtin_tools, effective_limits,
                                      instance_detail, is_local_model, iter_instances,
                                      load_manifest, mcp_tool_risk,
                                      roots, save_instance, skill_detail,
                                      skills_catalog, trash_instance)
from mora02_core._common import get_logger

log = get_logger("agents")

# Full paths rather than a prefix. The prefix form needed a route literally
# spelled "s" to produce /agents, which reads as a typo to anyone who has not
# been told; with a third route arriving it stops being worth the cleverness.
router = APIRouter(tags=["agents"])

# The roster as the mounts hold it: the platform root (agents/ in the repo:
# skills, tools, the reception desk) and this installation's root (data/agents/:
# every agent). The gateway has its own idea of which agents exist (see
# /agents); this is the other half -- the label, icon and description a person
# needs, which the gateway never stores. Both roots come from the environment
# (MORA02_AGENTS_DIR, MORA02_AGENTS_LOCAL_DIR).
ROOTS = roots()
AGENTS_DIR = ROOTS.platform

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
    return load_manifest(agent_id, ROOTS)


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


# The endpoints below read and write files and never await anything. They are
# plain `def` on purpose: FastAPI runs those in its threadpool, whereas an
# `async def` doing file I/O runs ON the event loop and stalls every other
# request -- a chat turn included -- for as long as the disk takes.
@router.get("/agents/roster")
def get_roster(include_inactive: bool = False):
    """The agents as people see them: label, icon, colour, description.

    Read by looking, exactly as the rollout does — one folder under
    ``instances/`` is one agent, and its folder name is its id. Nothing
    enumerates them, so an agent created in the builder appears here without
    anything else being edited. That is the whole of increment 3.

    Only ``active`` agents are returned unless ``include_inactive`` is set --
    the builder asks for all of them, the chat never does. ``main`` never
    appears: it is the gateway's reception desk, not an agent (agents/gateway.json).
    """
    if ROOTS.local is None:
        # A 503 naming the mount rather than an empty list: "no agents" and
        # "the directory was never mounted" look identical to a UI, and only
        # one of them is something an operator can fix.
        raise HTTPException(
            status_code=503,
            detail="no installation root — is /opt/mora02/data/agents mounted and "
                   "MORA02_AGENTS_LOCAL_DIR set for this container?",
        )

    agents = []
    try:
        folders = iter_instances(ROOTS)
    except StoreError as e:
        raise _store_error(e)
    for folder in folders:
        manifest = folder / "agent.json"
        if not manifest.is_file():
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue  # a broken manifest hides itself, never the others
        if not data.get("active", True) and not include_inactive:
            continue
        agents.append({
            "id": folder.name,
            "active": bool(data.get("active", True)),
            "model": data.get("model", ""),
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


# ---------------------------------------------------------------------------
# The builder's half: what an agent may be made of, one agent in full, and the
# rollout. Everything below writes files into the mounted roster or talks to
# the gateway through the library; nothing here knows the folder layout.
# ---------------------------------------------------------------------------

def _store_error(e: StoreError) -> HTTPException:
    # 422 for a manifest the store refuses, 404 for an agent that is not there.
    # The message is the store's own: it names the field and says what is wrong.
    code = 404 if str(e).startswith("no agent") else 422
    return HTTPException(status_code=code, detail=str(e))


@router.get("/agents/models")
async def get_models():
    """The models the gateway will accept in an agent's `model` field."""
    try:
        models = await gateway_models()
    except (AgentError, Exception) as e:
        raise HTTPException(status_code=502, detail=f"gateway model list unavailable: {e}")
    # The local entry's id is a port, not a weight (see _loaded_weights). What
    # a person choosing "local" is choosing is whatever llama-server has loaded
    # right now -- so that is what stands beside the entry, asked of the server.
    loaded = await _loaded_weights()
    for m in models:
        if m.get("local"):
            m["loaded"] = loaded
    return {"models": models}


@router.get("/agents/roots")
def get_roots():
    """Where things live, so the builder can say where an agent goes -- and say
    plainly when there is nowhere (no installation root mounted)."""
    return {"platform": str(ROOTS.platform),
            "local": str(ROOTS.local) if ROOTS.local else None,
            "can_create": ROOTS.local is not None}


@router.get("/agents/skills")
def get_skills():
    try:
        return {"skills": skills_catalog(ROOTS)}
    except StoreError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/agents/skills/{name}")
def get_skill(name: str):
    """One skill with its files, readable. What the agent reads, a person can."""
    try:
        return skill_detail(name, ROOTS)
    except StoreError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/agents/tools")
def get_tools():
    """Every tool an allow list may name, with what each one does.

    Two sources, deliberately. The house's MCP tools come from the live server
    in this very process -- a tool added to mcp_tools.py is in the builder
    without a second edit. The gateway's own tools come from agents/tools.json,
    curated, because only a person can write what `exec` means for an agent.
    Ids are what the allow list wants: MCP tools carry the server prefix.
    """
    from mcp_tools import TOOLS as _MCP_TOOLS  # local: the module is heavy at import
    server = "mora02"
    try:
        servers = json.loads((AGENTS_DIR / "mcp.json").read_text(encoding="utf-8"))
        names = [k for k in servers if not k.startswith("_")]
        if names:
            server = names[0]
    except (OSError, ValueError):
        pass
    mcp = [{
        "id": f"{server}__{t['name']}",
        "risk": mcp_tool_risk(t["name"]),
        "what": t.get("description", "")[:220],
        "source": "mcp",
    } for t in _MCP_TOOLS]
    builtin = [{**t, "source": "gateway"} for t in builtin_tools(ROOTS)]
    return {"tools": mcp + builtin}


@router.get("/agents/drift")
async def get_drift():
    """`agents-deploy.py --check` as a GET: what the rollout would change."""
    res = await asyncio.to_thread(deploy_mod.run, check=True, rt=ROOTS)
    if res["error"]:
        raise HTTPException(status_code=422, detail=res["error"])
    return res


@router.post("/agents/deploy")
async def post_deploy(agent: Optional[str] = None):
    """Render the roster into the gateway. Returns what changed and whether it
    took; 502 when the gateway refused, 422 when the roster itself is unfit."""
    res = await asyncio.to_thread(deploy_mod.run, check=False, only=agent, rt=ROOTS)
    if res["error"]:
        raise HTTPException(status_code=502 if res["applied"] or res["drift"] else 422,
                            detail=res["error"])
    return res


@router.get("/agents/{agent_id}/detail")
def get_detail(agent_id: str):
    try:
        return instance_detail(agent_id, ROOTS)
    except StoreError as e:
        raise _store_error(e)


class AgentSave(BaseModel):
    manifest: dict
    soul: Optional[str] = None
    soul_shared_with: Optional[str] = None
    # TOOLS.md / USER.md / IDENTITY.md: absent = untouched, "" = removed
    files: Optional[dict] = None


@router.put("/agents/{agent_id}")
def put_agent(agent_id: str, req: AgentSave):
    """Write one agent's folder. Saving does NOT roll out: the drift view shows
    what changed, and the person decides when the gateway follows. Two steps
    on purpose -- a form that deploys on every keystroke's save is a form that
    cannot be used to prepare anything."""
    try:
        return save_instance(agent_id, req.manifest, soul=req.soul,
                             soul_shared_with=req.soul_shared_with, files=req.files,
                             rt=ROOTS)
    except StoreError as e:
        raise _store_error(e)


@router.delete("/agents/{agent_id}")
def delete_agent(agent_id: str):
    """Move the folder to instances/.trash/. The gateway's copy goes at the next
    rollout, which reads the trash as the record of intent."""
    try:
        return trash_instance(agent_id, ROOTS)
    except StoreError as e:
        raise _store_error(e)


# Where llama.cpp answers. Same default as mora02_core.llm.models, and for the
# same reason: the container is called llama-server for every profile.
_QWEN_URL = auth.get("QWEN_URL", "http://llama-server:8080")


async def _loaded_weights() -> str:
    """Which model file is actually loaded, asked of the server itself.

    Why this exists at all. A local agent's `model` line reads
    "llama-local/current" and cannot say anything else: that is the id
    configured in the gateway's provider block, and an unconfigured one makes
    the agent fail to resolve. Meanwhile llama-server serves whatever GGUF is
    loaded and ignores the id in the request -- so the name in the manifest is
    a port, not a weight. Measured 2026-09-02: the manifest said qwen3-14b,
    llm-switch said qwen36-27b, and the server had Qwen3.6-27B.

    Asked of the server rather than read from llm-switch/current.json, because
    that file records what was REQUESTED. This reports what is LOADED, and the
    two can differ -- a switch that failed leaves the old weights answering
    under the new name.

    The wider point is the day's lesson. A model name nobody could check cost
    three research runs on a cloud model while everyone believed they were
    local. This puts the answer beside the answer.
    """
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{_QWEN_URL}/v1/models")
            data = r.json()["data"][0]
    except Exception:
        # Never delay or fail a turn over a label. Silence here reads as
        # "unknown" in the envelope, which is honest.
        return ""
    name = (data.get("id") or "").rsplit("/", 1)[-1]
    return name[:-5] if name.endswith(".gguf") else name


@router.get("/agent/progress")
async def get_agent_progress():
    """What the turn currently running has done so far.

    Polled by the Pilot while it waits. Deliberately a separate GET rather than
    a stream: the answer route is one request that takes minutes, and turning it
    into a stream would mean reshaping the gateway call underneath it. A poll
    reads registers that are already being kept, costs nothing on the model, and
    can be dropped without touching the turn.
    """
    return turn_progress()


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
    # Resolved through the store so a `same_as` reference lands here as the
    # other agent's numbers -- the coupling that keeps two comparable agents
    # comparable.
    limits = effective_limits(_manifest(agent_id), ROOTS)
    # The notebook needs to know which conversation it belongs to. Computed the
    # same way the gateway session is, so a follow-up question finds what the
    # previous one wrote down -- the thread held, the notes did not.
    sess = session_key(agent_id, req.conversation or "")
    started = begin_turn(limits if isinstance(limits, dict) else None, session=sess)
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
    finally:
        # Every exit, so a failed turn stops reporting itself as running.
        end_turn()

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
    # Which weights actually answered. For a cloud model the reported name IS
    # the model; for a local one it is the name of a port, so the server is
    # asked. Reported on every turn rather than only for local ones, because
    # "which model was that" is the question, not "was it local".
    # Locality is decided by the MANIFEST, never by what the gateway reports
    # back. Measured within an hour of writing this: OpenClaw returns the bare
    # id ("claude-sonnet-4-6", "qwen3-14b") with no provider prefix, so a test
    # for a missing slash called a cloud turn local and printed the local
    # weights under a Sonnet answer -- the very confusion this field exists to
    # end. The manifest carries the full "anthropic/..." or "llama-local/..."
    # string and is right here already.
    declared = str(_manifest(agent_id).get("model") or "")
    reported = str(result.get("model") or "")
    result["model_declared"] = declared or reported
    if is_local_model(declared):
        result["model_real"] = await _loaded_weights() or declared
    else:
        result["model_real"] = reported or declared
    # Carried across from earlier questions in the same conversation. Reported
    # separately from `notes`: what stands beside THIS answer is what was read
    # for it, and what merely still applies is a different claim.
    result["notes_carried"] = len(notes_earlier(sess, started))
    result["checks_carried"] = len(checks_earlier(sess, started))

    # Step 4 of the method, made visible whether or not the agent mentions it.
    # This is the whole point of the block: the two runs that missed the answer
    # both NAMED the gap in their notes and then walked past it, and nothing in
    # the output said so -- the report simply read as finished. So the envelope
    # states it instead. `checks` is what was verified at a source and what came
    # back; `open` is what the notes themselves flag as unestablished; and
    # `open_unchecked` is the difference -- the ones no `verify` call closed.
    #
    # WHAT THIS DOES NOT KNOW, and what its first real run taught: it never
    # reads the answer. Measured 2026-09-02, the ComfyUI turn -- one open point
    # was flagged here while the report had declared it in plain words ("Hinweis
    # zur Lücke: ... habe ich nicht direkt an der offiziellen WHL-Index-Seite
    # geprüft"), which is the second of the two legitimate endings. The agent
    # behaved better than the display credited it for.
    #
    # So this counts ONE thing: open points that were not verified at a source.
    # Whether the report declared them is a different question, and a crude word
    # match against the answer would answer it wrongly in the direction that
    # matters -- a false "declared" would hide exactly the case this was built
    # to catch. Left unmeasured on purpose until a run shows a point genuinely
    # passed over in silence, so the detector can be built against a real one.
    #
    # Zero is a legitimate value everywhere here. A turn that verified nothing
    # because nothing load-bearing was in doubt is fine. What is no longer
    # possible is for that to be indistinguishable from a turn that had three
    # open figures and said nothing.
    checks = checks_since(started)
    offen = open_notes(notes)
    closed = {(c.get("claim") or "")[:60] for c in checks}
    result["checks"] = checks
    result["checks_confirmed"] = sum(1 for c in checks
                                     if c.get("result") == "confirmed")
    result["open_points"] = offen
    result["open_unchecked"] = [o for o in offen
                                if (o.get("claim") or "")[:60] not in closed]
    # Weaker signal, shown separately so the strong warning stays strong: a
    # figure resting on one host that no verify call touched. Candidates, not
    # faults -- but this is the class the Blender turn's one real error fell
    # into, and nothing in the output had named it.
    _solo = single_source_notes(notes)
    result["one_source_family"] = _solo["one_family"]
    result["single_source_unchecked"] = [
        n for n in _solo["candidates"]
        if (n.get("claim") or "")[:60] not in closed
        and (n.get("claim") or "")[:60] not in {o.get("claim", "")[:60] for o in offen}
    ]

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
    if result["open_unchecked"]:
        # Says only what it knows. Whether the report declared the point is not
        # measured here -- see the note above.
        log.warning("agent %s left %s open point(s) unverified at a source",
                    agent_id, len(result["open_unchecked"]))
    if result["sources"]["read_count"] and not notes:
        # Not an error, but the exact shape of the failure that was measured:
        # pages read, nothing written down, restrictions lost on the way out.
        log.warning("agent %s read %s page(s) and took no notes",
                    agent_id, result["sources"]["read_count"])
    return result
