"""The verbs an agent may use, spoken as MCP.

Increment 2 of the agent layer gives the agent hands. This is the hand, and
what it CANNOT hold is the point of it.

Why not the built-in tools. The ``lobster`` tool inside OpenClaw cannot hold an
``input:`` gate at all, and an agent turn resolves its own ``approval:`` gates
(see ``mora02_core.pipeline.lobster``) -- so handing it over would dissolve HITL
from the inside. ``exec`` is worse: the tool bench measured five models reaching
for five different tools to force a gate, and a shell was the commonest. MCP is
the only path that adds exactly one capability and nothing else.

So this server offers ``flows_list``, ``flow_run`` and ``run_status`` -- and no
resume, no approve, no cancel.

Two more were added for the research agent: ``web_search`` and ``web_read``,
both against the LOCAL metasearch engine and the open web via
``mora02_core.web``. They are granted separately, so an agent can read the web
without touching pipelines and vice versa -- the line that lets a
reading-only agent later run on a cloud model while a steering one may not. Pillar 6 of the plan ("the agent does not release
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

import asyncio
import json
import os
import time
from collections import deque
from typing import Any

import httpx
from fastapi import APIRouter, Request, Response

from mora02_core import web
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

# What the tools may put into the model's context, and it is a hard budget.
#
# MEASURED: llama-server runs at LLAMA_ARG_CTX_SIZE=32768 while OpenClaw's model
# entry claims contextWindow 128000. The gateway therefore budgets against four
# times the room that exists, never trims, and a turn that read five pages
# simply produced no answer -- ~27k tokens of input against a 32k ceiling, with
# the reply still to come. Same trap as the provider name that always says
# qwen3-14b: the number on the card is not the number in the machine.
#
# So the payloads are sized for 32k, not for the advertised 128k. The notes are
# what makes that affordable -- meaning is carried forward in a few hundred
# characters instead of in the raw page, which is the whole point of taking
# them. Every cut is still reported, and max_chars raises it per call when a
# page really is worth reading whole.
# These are DEFAULTS, sized for a 32k local window. An agent may raise them in
# its own agent.json, and one on a large-context model should.
#
# WHY PER AGENT: measured side by side on the same question and the same model.
# Claude's own harness answered with Sonnet in under a minute and two search
# operations. Ours, with Sonnet, took 28 tool calls and over eight minutes and
# never finished -- because these limits, cut for a 32k window, forced five read
# calls to see what one could have carried. Every call is a full round trip
# (model -> gateway -> service -> web -> back), so a narrow payload does not
# save time, it multiplies it.
#
# A ceiling sized for one model throttles another. Same lesson as the context
# window, from the other direction.
_DEFAULTS = {
    "page_chars": 2500,
    "max_queries": 5,
    "max_urls": 3,
    "snippet_chars": 160,       # a snippet decides whether to open a page, no more
    "results_per_query": 5,
    # Ceilings for the WHOLE turn, not per call. Raising what one call may carry
    # says nothing about how many calls there will be -- eight pages per read
    # and five reads is forty pages. A budget makes a turn's cost predictable,
    # and it is spent rather than forbidden: the tools report what is left and
    # say plainly when it is gone.
    "max_pages_total": 12,
    "max_searches_total": 6,
}

_LIMITS: dict = dict(_DEFAULTS)


def _lim(key: str) -> int:
    return int(_LIMITS.get(key) or _DEFAULTS[key])

# ---------------------------------------------------------------------------
# What the tools actually touched
# ---------------------------------------------------------------------------
# A model completes a URL like it completes any other text. Measured: of four
# citations in one research answer, three were dead -- two 404, one that did not
# resolve at all. A footnote that LOOKS checkable is worse than none, because it
# invites the trust it cannot carry, and it defeats every rule written to make
# an answer verifiable.
#
# A rule against it is a request to the very faculty that produces it. So this
# records what the tools really handed out and really fetched. A citation that
# is not in this list was not read -- visible at a glance, without anyone having
# to click.
#
# Attribution is by time window, not by session: OpenClaw sends no turn id with
# an MCP call, and this process serves both the agent route and /mcp, so calls
# made during a turn fall between its start and end. Two turns running at once
# would blur -- acceptable here, and named rather than hidden.
_SEEN: deque = deque(maxlen=600)

# What the agent wrote down while reading. Measured across a day of use: rules
# the machinery enforces are kept, rules that are only prose are followed when
# convenient. "No gate tool exists" held every time; "cite only URLs a tool gave
# you" held as soon as the real ones were displayed; "take notes as you read"
# was rolled out, quoted back verbatim on request, and ignored in the next three
# reports -- and with it went a closure notice, a seasonal caveat and a mountain
# 640 metres too short.
#
# So noting becomes an ACT with a record, not a resolution. A claim in an answer
# with no note behind it is then as visible as a fabricated URL is now.
_NOTES: deque = deque(maxlen=300)

# Where the current turn began. The MCP surface has no turn id -- OpenClaw sends
# none -- so the agent route stamps this when it starts one, and the note tools
# read it. Same time-window approach as the URL record above, with the same
# limitation: two turns at once would blur.
_TURN_T0: float = 0.0
_REVIEWED: float = 0.0
_SPENT: dict = {"pages": 0, "searches": 0}


def begin_turn(limits: dict | None = None) -> float:
    """Called by the agent route when a turn starts.

    Carries the acting agent's payload limits, because the MCP surface has no
    way to know who is calling -- the same reason the turn boundary is stamped
    here at all.
    """
    global _TURN_T0, _LIMITS, _SPENT
    _TURN_T0 = time.time()
    _LIMITS = {**_DEFAULTS, **(limits or {})}
    _SPENT = {"pages": 0, "searches": 0}
    return _TURN_T0


def reviewed_this_turn() -> bool:
    """Did the agent look at its own notes before answering?"""
    return _REVIEWED >= _TURN_T0 > 0


def _remember(kind: str, url: str, ok: bool = True) -> None:
    if url:
        _SEEN.append((time.time(), kind, url, ok))


def notes_since(t0: float) -> list[dict]:
    return [n for ts, n in list(_NOTES) if ts >= t0]


def urls_since(t0: float) -> dict:
    """Which addresses the tools produced after ``t0``.

    ``read`` is what a claim may rest on -- those pages were actually fetched.
    ``found`` were only ever offered by a search engine, so a claim citing one
    without reading it rests on a snippet.
    """
    read, found, failed = [], [], []
    for ts, kind, url, ok in list(_SEEN):
        if ts < t0:
            continue
        if kind == "read":
            (read if ok else failed).append(url)
        else:
            found.append(url)
    seen = set()
    read = [u for u in read if not (u in seen or seen.add(u))]
    return {
        "read": read[:20],
        "read_count": len(read),
        "found_count": len(set(found)),
        "failed": failed[:5],
    }


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
        "name": "web_search",
        "description": (
            "Use this to search the web whenever a question needs information "
            "you do not already have. Pass SEVERAL queries at once — different "
            "wordings, synonyms, the English term, a vendor name, the opposing "
            "view — because one phrasing finds one corner of a subject. Results "
            "come back grouped per query, each with its title, URL and a "
            "snippet. The URL is what makes a later claim checkable, so keep it "
            "with whatever you take from a result."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "queries": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Several search queries, run at once — use the room you have.",
                },
            },
            "required": ["queries"],
        },
    },
    {
        "name": "web_read",
        "description": (
            "Use this to read pages you found with web_search, when a snippet "
            "is not enough to answer. Pass several URLs at once. Returns the "
            "readable text of each, and says so when a page was cut short or "
            "could not be read — a page that failed is reported as failed, "
            "never as empty."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Several page URLs, read at once — every call is a round trip, so send them together.",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Per page. Raise it "
                                   "when a cut page says it left something behind.",
                },
            },
            "required": ["urls"],
        },
    },
    {
        "name": "note",
        "description": (
            "Use this right after reading, while the pages are still in front of "
            "you and BEFORE opening more. Record ALL findings from what you just "
            "read in ONE call — pass the whole list. Each note says what the "
            "source claims, which source it was, and above all any restriction "
            "attached: a date, a season, a region, a version, a closure, a "
            "licence limit, a 'but only if'. What is written down does not have "
            "to survive being remembered."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "notes": {
                    "type": "array",
                    "description": "All findings from this reading round, at once.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "claim": {"type": "string",
                                      "description": "What the source says, in one sentence."},
                            "source": {"type": "string",
                                       "description": "The URL it came from."},
                            "restriction": {"type": "string",
                                            "description": "The limit attached: date, season, "
                                                           "region, version, closure, licence."},
                        },
                        "required": ["claim", "source"],
                    },
                },
            },
            "required": ["notes"],
        },
    },
    {
        "name": "notes_review",
        "description": (
            "Call this immediately BEFORE writing your answer, every time you "
            "have taken notes. It returns everything you noted during this "
            "task, with the restrictions attached. Build the answer from what "
            "comes back rather than from what you remember of the pages — by "
            "the time you compose, the reading is twenty tool calls behind you "
            "and the qualifiers are the first thing to fade. Takes no arguments."
        ),
        "inputSchema": {"type": "object", "properties": {}, "required": []},
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


async def _web_search(queries: list) -> dict:
    """Several angles at once. A failed angle stays distinguishable from an empty one."""
    queries = [q for q in queries if isinstance(q, str) and q.strip()][:_lim("max_queries")]
    if not queries:
        return {"error": "web_search needs at least one query in 'queries'"}
    if _lim("max_searches_total") - _SPENT["searches"] <= 0:
        return {"error": "Such-Budget für diesen Zug erschöpft.",
                "hint": "Nicht weitersuchen. Schreibe die Antwort aus dem, was du "
                        "hast, und sag im Bericht, dass du aus Budgetgründen "
                        "aufgehört hast — das ist ein gültiger Grund und gehört "
                        "genannt."}
    _SPENT["searches"] += 1
    try:
        found = await web.search_many(queries, limit=_lim("results_per_query"))
    except web.WebError as e:
        return {"error": str(e)}
    for block in found.get("per_query", []):
        for r in block.get("results", []):
            _remember("found", r.get("url", ""))
            # A snippet exists to decide whether the page is worth opening. Kept
            # whole it costs context that the answer needs later.
            if len(r.get("content") or "") > _lim("snippet_chars"):
                r["content"] = r["content"][:_lim("snippet_chars")] + "…"

    # If every angle failed, that is not a thin result — it is a broken search,
    # and saying so is what keeps a model from reporting "nothing exists".
    if found["unique_urls"] == 0 and len(found["failed"]) == len(queries):
        first = next((b.get("error") for b in found["per_query"] if b.get("error")), "")
        return {
            "error": f"no angle could be searched — {first}",
            "queries": queries,
            "note": "This is a failed search, not an empty one. Say so; do not "
                    "answer from memory as if the search had returned nothing.",
        }
    found["budget_left"] = {
        "searches": _lim("max_searches_total") - _SPENT["searches"],
        "pages": _lim("max_pages_total") - _SPENT["pages"],
    }
    return found


async def _web_read(urls: list, max_chars: int | None) -> dict:
    """Read several pages. Each one reports its own outcome."""
    urls = [u for u in urls if isinstance(u, str) and u.strip()][:_lim("max_urls")]
    if not urls:
        return {"error": "web_read needs at least one url in 'urls'"}
    left = _lim("max_pages_total") - _SPENT["pages"]
    if left <= 0:
        return {"error": "Lese-Budget für diesen Zug erschöpft.",
                "hint": "Keine weiteren Seiten. Rufe `notes_review` auf und "
                        "schreibe die Antwort aus deinen Notizen. Sag im "
                        "Bericht, dass du aus Budgetgründen aufgehört hast."}
    urls = urls[:left]
    _SPENT["pages"] += len(urls)
    cap = int(max_chars or _lim("page_chars"))

    async def one(u: str) -> dict:
        try:
            return await web.fetch(u, max_chars=cap)
        except web.WebError as e:
            return {"url": u, "error": str(e)}

    pages = await asyncio.gather(*(one(u) for u in urls))
    for pg in pages:
        _remember("read", pg.get("url", ""), ok=not pg.get("error"))
    failed = [p["url"] for p in pages if p.get("error")]
    if len(failed) == len(pages):
        return {"error": "none of the pages could be read", "pages": pages}
    # The reminder travels WITH the page, not in a system prompt read once at
    # the start. That is the difference between an instruction and a prompt: it
    # arrives at the moment the act is due.
    return {
        "pages": pages, "read": len(pages) - len(failed), "failed": failed,
        "budget_left": {"pages": _lim("max_pages_total") - _SPENT["pages"],
                        "searches": _lim("max_searches_total") - _SPENT["searches"]},
        "next": "Jetzt je gelesener Seite `note` aufrufen — was sie zur Frage "
                "sagt und welche Einschränkung daran hängt (Datum, Saison, "
                "Version, Sperrung, Lizenz) — ALLE Funde in EINEM Aufruf, als "
                "Liste. Erst danach weiterlesen. Vor dem Schreiben dann "
                "`notes_review`.",
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
    if name == "notes_review":
        global _REVIEWED
        _REVIEWED = time.time()
        notes = notes_since(_TURN_T0)
        limits = [n for n in notes if n.get("restriction")]
        if not notes:
            return {"notes": [], "hint": "Nichts notiert. Wenn du Seiten gelesen "
                                         "hast, fehlt die Grundlage der Antwort."}
        return {
            "notes": notes,
            "count": len(notes),
            "with_restriction": len(limits),
            "hint": "Schreibe die Antwort JETZT aus diesen Notizen. Jede "
                    "Einschränkung reist mit ihrer Behauptung mit — eine "
                    "Empfehlung, deren Einschränkung weggelassen wurde, ist "
                    "nicht kürzer, sondern falsch. Was hier nicht steht, hast "
                    "du nicht gelesen.",
        }
    if name == "note":
        # A list, not one call per finding. The tool bench measured this model
        # holding eight hops in four runs of five; note-per-finding pushed real
        # turns to twelve calls and they started dying without an answer. Same
        # principle as web_search and web_read: fewer, fatter hops. A single
        # note is still accepted -- an agent that sends one is not wrong, just
        # slower.
        raw = arguments.get("notes")
        if not isinstance(raw, list):
            raw = [arguments] if arguments.get("claim") else []
        kept = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            claim = (item.get("claim") or "").strip()
            if not claim:
                continue
            note = {
                "claim": claim[:400],
                "source": (item.get("source") or "").strip()[:300],
                "restriction": (item.get("restriction") or "").strip()[:300],
            }
            _NOTES.append((time.time(), note))
            kept.append(note)
        if not kept:
            return {"error": "note needs a 'notes' list, each with a claim"}
        return {"ok": True, "noted": len(kept),
                "notes_so_far": len(notes_since(_TURN_T0)),
                "hint": "Weiterlesen oder direkt zum Schluss. Unmittelbar VOR dem "
                        "Schreiben `notes_review` aufrufen und die Antwort daraus "
                        "bauen."}
    if name == "web_search":
        qs = arguments.get("queries")
        return await _web_search(qs if isinstance(qs, list) else [])
    if name == "web_read":
        us = arguments.get("urls")
        return await _web_read(us if isinstance(us, list) else [],
                               arguments.get("max_chars"))
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
