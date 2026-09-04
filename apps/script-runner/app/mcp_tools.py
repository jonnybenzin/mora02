"""The verbs an agent may use, spoken as MCP.

Increment 2 of the agent layer gives the agent hands. This is the hand, and
what it CANNOT hold is the point of it.

Why not the built-in tools. The ``lobster`` tool inside OpenClaw cannot hold an
``input:`` gate at all, and an agent turn resolves its own ``approval:`` gates
(see ``mora02_core.pipeline.lobster``) -- so handing it over would dissolve HITL
from the inside. ``exec`` is worse: the tool bench measured five models reaching
for five different tools to force a gate, and a shell was the commonest. MCP is
the only path that adds exactly one capability and nothing else.

So of the pipeline this server offers ``flows_list``, ``flow_run`` and
``run_status`` -- and no resume, no approve, no cancel.

The research agent added ``web_search`` and ``web_read``, both against the
LOCAL metasearch engine and the open web via ``mora02_core.web``, and the
notebook that keeps a long turn honest: ``note``, ``notes_review`` and
``verify``. Eight in all; ``agents/tools.json`` says which of them merely read
and which act.

They are granted separately, so an agent can read the web without touching
pipelines and vice versa -- the line that lets a reading-only agent run on a
cloud model while a steering one may not. Pillar 6 of the plan ("the agent
does not release a gate") stops being a request to the model and becomes a
property of its tool surface. ``flow_run`` therefore also DROPS the ``resume_token`` that
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
import re
import time
from collections import deque
from typing import Any

import httpx
from fastapi import APIRouter, Request, Response

from mora02_core import web
from mora02_core.agents.store import LIMIT_DEFAULTS
from mora02_core._common import get_logger
from mora02_core.pipeline import spec as pipeline_spec
from mora02_core.pipeline import (
    PipelineError,
    run_pipeline_spec,
    runlog as pipeline_runlog,
)

log = get_logger("mcp")

router = APIRouter(tags=["mcp"])

# Where named specs live -- the same directory /pipeline/flows reads, so the
# agent picks from exactly the library a human sees in the Pilot.
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
# The numbers themselves live with the keys, in mora02_core.agents.store, so
# the form that sets them, the check that validates them and the tools that
# spend them cannot drift apart. Note what the two `_total` ones mean: ceilings
# for the WHOLE turn, not per call. Raising what one call may carry says
# nothing about how many calls there will be -- eight pages per read and five
# reads is forty pages. A budget makes a turn's cost predictable, and it is
# spent rather than forbidden: the tools report what is left and say plainly
# when it is gone.
_DEFAULTS = dict(LIMIT_DEFAULTS)

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

# What the agent checked at its SOURCE, and what came back. Step 4 of the method
# ("check the load-bearing facts at the source") was the only one of the five
# without a tool: notes had `note`, re-reading had `notes_review`, sources had
# `web_read` -- and each of those leaves a trace beside the answer. Step 4 was a
# paragraph asking for behaviour, so it never appeared in a report and nobody
# noticed.
#
# Measured 2026-09-01, twice, on the strongest model available: both research
# runs named their own gap in plain words -- "genaue Tiefe/Breite fuer die
# DeLonghi-Modelle nicht aus den Quellen bestaetigt" -- and stopped there. A
# hand check the next morning found the missing figure at a price comparison
# site in two minutes, and it changed the recommendation. Neither the searching
# nor the judging failed. The CLOSING step did, and it failed silently.
#
# A check is therefore an act with a record, like a note. And unlike a note it
# is verified against what the tools really fetched (see `_read_urls_since`):
# a check may not be asserted, only performed.
_CHECKS: deque = deque(maxlen=200)

# Which restrictions mark a note as an OPEN question rather than a caveat.
# Deliberately crude -- its job is to raise candidates, not to be right. Both
# languages, because the agent answers in the language it is addressed in.
# German puts the negation far from the verb it negates -- the first real note
# this was tried on read "nicht AUS DEN QUELLEN bestaetigt" and slipped straight
# through a pattern that wanted the two words adjacent. So a few words are
# allowed to stand between them, in both languages.
_GAP = r"(?:\S+\s+){0,4}"
_OPEN_RX = re.compile(
    r"nicht\s+" + _GAP + r"(?:best(?:ä|ae|a)tigt|belegt|gefunden|genannt"
    r"|verifiziert|auffindbar|nachgewiesen|gepr(?:ü|ue)ft)"
    r"|kein(?:e|er|en)?\s+" + _GAP + r"(?:angabe|angaben|beleg|quelle|nachweis)"
    r"|unbest(?:ä|ae|a)tigt|unbelegt|unklar|ungekl(?:ä|ae)rt"
    r"|widerspr(?:ü|ue)chlich|ungepr(?:ü|ue)ft|fraglich"
    r"|not\s+" + _GAP + r"(?:confirmed|found|stated|verified|listed|established)"
    r"|unconfirmed|unverified|unclear|contradictor|no\s+source",
    re.I,
)

# Where the current turn began. The MCP surface has no turn id -- OpenClaw sends
# none -- so the agent route stamps this when it starts one, and the note tools
# read it. Same time-window approach as the URL record above, with the same
# limitation: two turns at once would blur.
_TURN_T0: float = 0.0
# Which CONVERSATION the current turn belongs to. The time window alone answers
# "what was noted in this turn"; it cannot answer "what did we establish two
# questions ago", and a follow-up question was measured arriving with an empty
# notebook while the conversation thread itself held fine. The gateway sends no
# session id with an MCP call, so the agent route stamps this the same way it
# stamps the turn start, from `session_key(agent, conversation)` -- a pure
# function, so the same Pilot conversation always maps to the same string.
#
# Still in-process: a rebuild empties the notebook while OpenClaw keeps the
# thread. Acceptable and named -- notes are working material for a chain of
# questions, not a record. Persisting them is a separate decision.
_SESSION: str = ""
# When the route stopped waiting. Without it `turn_progress` would report a turn
# as running forever after it ended -- true of the registers, false of the
# world, and the kind of stale "yes" that is worse than no answer.
_TURN_END: float = 0.0
_REVIEWED: float = 0.0
_SPENT: dict = {"pages": 0, "searches": 0}


class TurnBusy(RuntimeError):
    """A turn is already running and its registers are not free."""


# Above this, a turn that never ended is a leak, not a long read. No real turn
# comes close: the route's own timeout bounds it, and the longest configured
# one is minutes. Without a ceiling, one turn whose end_turn never ran would
# answer 409 to every turn after it, for the life of the process.
_TURN_CEILING_S = 3600


def turn_running() -> bool:
    """Is a turn open right now? (started, not yet ended, not ancient)"""
    return (_TURN_T0 > 0 and _TURN_END < _TURN_T0
            and time.time() - _TURN_T0 < _TURN_CEILING_S)


def begin_turn(limits: dict | None = None, session: str = "") -> float:
    """Called by the agent route when a turn starts.

    Carries the acting agent's payload limits, because the MCP surface has no
    way to know who is calling -- the same reason the turn boundary is stamped
    here at all. A JSON-RPC message carries no caller identity, so there is
    exactly one set of registers, and one turn may hold them.

    Starting a second turn over a running one is refused rather than done.
    It used to overwrite them, and every consequence was silent: the running
    turn's notes were stamped with the OTHER conversation and surfaced there
    later as established fact, its page budget went back to full, its `verify`
    of a page it had read was rejected as not-fetched-this-turn, and whichever
    turn ended first reported both as finished (review 2, finding 1). The
    agent route serialises turns; this is the guard under it.
    """
    global _TURN_T0, _LIMITS, _SPENT, _SESSION, _TURN_END
    if turn_running():
        raise TurnBusy(
            f"a turn is already running (session {_SESSION or 'unknown'}, "
            f"{time.time() - _TURN_T0:.0f}s ago)"
        )
    _TURN_T0 = time.time()
    _TURN_END = 0.0
    _LIMITS = {**_DEFAULTS, **(limits or {})}
    _SPENT = {"pages": 0, "searches": 0}
    _SESSION = session or ""
    return _TURN_T0


def end_turn() -> None:
    """The route is no longer waiting. Called on every exit, success or not."""
    global _TURN_END
    _TURN_END = time.time()


def reviewed_this_turn() -> bool:
    """Did the agent look at its own notes before answering?"""
    return _REVIEWED >= _TURN_T0 > 0


def _remember(kind: str, url: str, ok: bool = True) -> None:
    if url:
        _SEEN.append((time.time(), kind, url, ok))


def notes_since(t0: float) -> list[dict]:
    """What was written down in THIS turn. Unchanged meaning on purpose: it is
    what stands beside this answer."""
    return [n for ts, sess, n in list(_NOTES) if ts >= t0]


def notes_earlier(session: str, t0: float, cap: int = 12) -> list[dict]:
    """What the same conversation established BEFORE this turn, newest first.

    Capped, and the cap is the whole design decision. Everything ever noted in a
    long conversation would crowd out the reading of the current one; twelve is
    enough to carry the qualifiers a follow-up depends on. Without a session an
    empty list, never a guess -- two conversations blurring into one another is
    worse than a lost note.
    """
    if not session:
        return []
    out = [n for ts, sess, n in list(_NOTES) if sess == session and ts < t0]
    return out[-cap:][::-1]


def checks_since(t0: float) -> list[dict]:
    return [c for ts, sess, c in list(_CHECKS) if ts >= t0]


def checks_earlier(session: str, t0: float, cap: int = 12) -> list[dict]:
    """Facts already verified earlier in the same conversation.

    Carried for the same reason as the notes, and with more force: a figure
    confirmed at its source two questions ago does not become unconfirmed
    because someone asked a follow-up, and re-fetching it is a round trip spent
    on something already known.
    """
    if not session:
        return []
    out = [c for ts, sess, c in list(_CHECKS) if sess == session and ts < t0]
    return out[-cap:][::-1]


# Words too common to mean two notes are talking about the same thing.
_STOP = frozenset("""
oder aber nicht wird werden sind auch kann koennen können laut nach ueber über
unter eine einer eines einem einen dass diese dieser dieses beim vom zum zur
this that with from which have been also more than only some most best when
does will they there their been such into over about
""".split())

# What makes a claim worth verifying at all. Step 4 names the kinds itself:
# a version, a size, a price, a limit, a licence. All of them carry a figure,
# and a claim without one is usually a description rather than a load-bearing
# fact.
_FIG_RX = re.compile(r"\d")
# A version or a measurement outranks a bare year: "5.2.1", "2 GB", "24,6 cm".
_STRONG_RX = re.compile(
    r"\d+\.\d+|\d+[,.]\d+\s*(?:cm|mm|gb|mb|kg|g|w|wh|%|€|eur)"
    r"|\d+\s*(?:gb|mb|cm|mm|kg|wh|€|eur|%)", re.I)


def _host(url: str) -> str:
    m = re.match(r"(?:https?://)?(?:www\.)?([^/]+)", (url or "").strip().lower())
    return m.group(1) if m else ""


def _tokens(text: str) -> set:
    return {w for w in re.findall(r"[\w.,]{4,}", (text or "").lower())
            if w not in _STOP}


def single_source_notes(notes: list[dict], cap: int = 3) -> dict:
    """Which figures rest on one host — and whether that says anything.

    WHAT THIS WAS PROPOSED FOR, AND WHY THAT FAILED. It was meant to catch the
    one real error measured on 2026-09-02: the Blender turn wrote "Intel-Macs
    werden seit Blender 4.5 LTS nicht mehr unterstuetzt", when 4.5 LTS was the
    LAST release WITH Intel support and the cut is 5.0. The idea was that a
    claim no second source echoes is the one to verify.

    Tested against that turn's actual six notes: ALL SIX qualified. A turn that
    does what step 4 asks -- read the vendor's own pages -- makes almost
    everything single-sourced, and for a version number one authoritative source
    is not a shortage, it is the right answer. Worse, the error was not
    under-sourced at all. It was MISREAD: the page said one thing and the note
    said its opposite. Counting sources cannot catch a misreading, however many
    sources there are.

    So the detector was kept and its claim reduced to what it can support. When
    the uncorroborated figures are a MINORITY, naming them is a real hint: the
    turn had several independent sources and these few stood apart. When they
    are most of the turn, that is a fact about the turn -- one source family --
    and it is reported as that single sentence instead of as a list of
    candidates, because a list where everything is flagged flags nothing.

    Deliberately NOT built: a heuristic for version-boundary phrasing ("seit",
    "letzte Version mit"), which would have caught this one case. Building it
    now would be tuning the instrument on the single example it is meant to
    generalise past.

    Returns ``{"candidates": [...], "one_family": bool, "total": int}``.
    """
    def whole(n: dict) -> str:
        return f"{n.get('claim') or ''} {n.get('restriction') or ''}"

    rich = [(n, _tokens(whole(n))) for n in notes if _FIG_RX.search(whole(n))]
    alone = []
    for note, toks in rich:
        host = _host(note.get("source"))
        if not any(len(toks & ot) >= 2 and _host(o.get("source")) != host
                   for o, ot in rich if o is not note):
            alone.append(note)

    # Selective or not. Two thirds is where a list stops distinguishing
    # anything; below it the few that stand apart are worth a look.
    one_family = bool(rich) and len(alone) > (2 * len(rich)) / 3
    if one_family:
        return {"candidates": [], "one_family": True, "total": len(alone)}

    alone.sort(key=lambda n: 0 if _STRONG_RX.search(whole(n)) else 1)
    return {
        "candidates": [{"claim": (n.get("claim") or "")[:200],
                        "source": n.get("source", ""),
                        "reason": "single source"} for n in alone[:cap]],
        "one_family": False,
        "total": len(alone),
    }


def open_notes(notes: list[dict], cap: int = 3) -> list[dict]:
    """Notes whose restriction says the figure was never actually established.

    Capped on purpose. Every open point turned into a duty is another tool call,
    and long chains were measured ending in no answer at all. Three is what a
    recommendation usually rests on; beyond that the honest move is to report
    them as open, which is a full outcome here and not the lesser one.
    """
    out = []
    for n in notes:
        if _OPEN_RX.search(n.get("restriction") or ""):
            out.append({"claim": n.get("claim", "")[:200],
                        "source": n.get("source", ""),
                        "restriction": n.get("restriction", "")[:160]})
        if len(out) >= cap:
            break
    return out


def _norm_url(u: str) -> str:
    """Loose enough that a check is not refused over a trailing slash."""
    u = (u or "").strip().lower()
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    return u.rstrip("/")


def _read_urls_since(t0: float, ok_only: bool = True) -> set:
    """Every address actually FETCHED this turn, normalised, untruncated.

    `urls_since` cuts its list for display; this one must not, because it
    decides whether a check is accepted.

    ``ok_only=False`` also returns the ones that FAILED, and that distinction
    carries a finding of its own. Measured 2026-09-02 by hand: four of ten
    fetches were refused outright (403), and the manufacturer's own page --
    the canonical place to verify a specification -- served nothing but
    ``VersuniB2CApp``, because it assembles itself in the browser. A tool that
    turns HTML into text can look up nothing there. So "not findable at the
    source" must stay reachable for a page that would not open, or the honest
    outcome becomes the one the machinery forbids.
    """
    return {_norm_url(u) for ts, kind, u, ok in list(_SEEN)
            if ts >= t0 and kind == "read" and (ok or not ok_only)}


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


def turn_progress() -> dict:
    """What the running turn has done so far, from records that already exist.

    Nothing new is measured here. Every field is read out of the same registers
    the answer envelope is built from -- which is the point: a turn was opaque
    for three minutes while the service knew, second by second, what it was
    doing. Measured 2026-09-02: 53 s for a light question, 194 s for one with
    five source checks, and in both the person saw a typing dot.

    `idle_s` is the field worth reading. Tool calls come in bursts; the gaps
    between them are the model composing. A gap of a few seconds is thinking, a
    gap of two minutes is a turn that may never come back, and until now those
    two looked identical from outside.

    Same limitation as the rest of this module, named rather than hidden: there
    is one set of registers, so two turns at once would blur into each other.
    """
    if not _TURN_T0 or _TURN_END >= _TURN_T0:
        return {"running": False}
    now = time.time()
    events = [(ts, kind, url, ok) for ts, kind, url, ok in list(_SEEN) if ts >= _TURN_T0]
    note_ts = [ts for ts, _sess, _n in list(_NOTES) if ts >= _TURN_T0]
    check_ts = [ts for ts, _sess, _c in list(_CHECKS) if ts >= _TURN_T0]
    read = [u for _ts, kind, u, ok in events if kind == "read" and ok]

    last = max([ts for ts, *_ in events] + note_ts + check_ts
               + ([_REVIEWED] if _REVIEWED >= _TURN_T0 else []) + [_TURN_T0])

    # What it is doing, in the order the method does it. Derived from which
    # record moved last rather than from anything the model says about itself.
    if _REVIEWED >= _TURN_T0 and _REVIEWED >= last:
        phase = "writing the answer"
    elif check_ts and max(check_ts) >= last:
        phase = "checking at the source"
    elif note_ts and max(note_ts) >= last:
        phase = "taking notes"
    elif events and events[-1][1] == "read":
        phase = "reading pages"
    elif events:
        phase = "searching"
    else:
        phase = "thinking"

    return {
        "running": True,
        "elapsed_s": round(now - _TURN_T0, 1),
        "idle_s": round(now - last, 1),
        "phase": phase,
        "searches": _SPENT.get("searches", 0),
        "searches_max": _lim("max_searches_total"),
        "pages": _SPENT.get("pages", 0),
        "pages_max": _lim("max_pages_total"),
        "notes": len(note_ts),
        "checks": len(check_ts),
        "reviewed": _REVIEWED >= _TURN_T0,
        "last_read": read[-1] if read else "",
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
            "to survive being remembered. "
            "AND: when the page you just read IS the source of a figure — the "
            "maker's own release page, the register, the repository — add "
            "`result` to that note and the figure is thereby checked at its "
            "source: 'confirmed' if the page says it, 'contradicted' if it "
            "says something else, 'not_found' if it does not have it or "
            "would not load. That is the difference between a figure you read "
            "somewhere and one you can stand behind, and it costs no extra call."
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
                            "result": {"type": "string",
                                       "enum": ["confirmed", "contradicted",
                                                "not_found"],
                                       "description": "Only when this page IS the "
                                                      "source of the figure: what it "
                                                      "did with it. Makes the note a "
                                                      "source check."},
                            "detail": {"type": "string",
                                       "description": "With `result`: what the page "
                                                      "actually said."},
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
        "name": "verify",
        # A MOMENT, not a judgement. The first wording asked the model to
        # decide "which facts would the recommendation be WRONG without" before
        # reaching for the tool, and two local runs never reached for it at all
        # -- with the window doubled in between, so it was not a matter of room.
        # `note` in the same prompt fired every single time, and the difference
        # between them is the trigger: note names an instant tied to another
        # tool ("right after reading, before opening more"), verify named a
        # deliberation. A smaller model follows a clock, not a criterion.
        "description": (
            "Use this right after a web_read that settled a FIGURE you will put "
            "in your answer — a version, a date, a price, a size, a limit, a "
            "licence. Same moment as `note`, usually the same reading: while "
            "the page is still in front of you, record where the figure came "
            "from and what the page did with it. Report ALL of them in ONE "
            "call. Three results count and all three are worth reporting: "
            "'confirmed' (the page says it), 'contradicted' (the page says "
            "something else), 'not_found' (the page does not have it, or "
            "would not load) — a decisive figure that is NOT at its source is "
            "often the most useful line in a report. The source must be a page "
            "you fetched this turn."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "checks": {
                    "type": "array",
                    "description": "Every load-bearing fact you checked, at once.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "claim": {"type": "string",
                                      "description": "The fact the recommendation "
                                                     "rests on, in one sentence."},
                            "source": {"type": "string",
                                       "description": "URL of the source you went "
                                                      "to. Must be one you fetched "
                                                      "with web_read this turn."},
                            "result": {"type": "string",
                                       "enum": ["confirmed", "contradicted",
                                                "not_found"],
                                       "description": "What the source said."},
                            "detail": {"type": "string",
                                       "description": "What it actually said — the "
                                                      "figure, or what contradicted."},
                        },
                        "required": ["claim", "source", "result"],
                    },
                },
            },
            "required": ["checks"],
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


def _text(item: dict, key: str) -> str:
    """One field of a model-supplied item, as text.

    Every argument on this surface was written by a language model, which is
    free to send a number where the schema says string, a list where it says
    scalar, or nothing at all. `(item.get(k) or "").strip()` assumed a string
    and turned `{"claim": 42}` into an AttributeError -- an HTTP 500 for the
    whole call, with the items before it in the batch already recorded, so the
    retry counted them twice (review 2, finding 4).

    A scalar is taken as its text; a list or object is not a field value and
    reads as absent. Nothing here raises.
    """
    v = item.get(key)
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, bool) or v is None or isinstance(v, (list, dict, tuple, set)):
        return ""
    return str(v).strip()


async def _flows_list() -> dict:
    # Off the event loop: this runs DURING a turn, which is exactly when the
    # loop also has to serve that turn's other tool calls and the Pilot's
    # two-second progress poll. A directory listing plus a json.load per spec
    # is small but it is disk, and disk on the loop stops everything.
    return await asyncio.to_thread(_flows_list_sync)


def _flows_list_sync() -> dict:
    # The directory has one reader now, in mora02_core.pipeline.spec: this used
    # to be a fourth copy, and the only one that checked a parsed file is
    # actually an object (review 3, 2026-09-04).
    flows = [
        {
            "name": data.get("name") or path.stem,
            "description": data.get("description", ""),
            "steps": len(data.get("steps", [])),
            "tags": data.get("tags", []),
        }
        for path, data in pipeline_spec.list_specs()
    ]
    return {"flows": flows, "count": len(flows)}


async def _flow_run(flow: str, args: dict | None) -> dict:
    """Start a named flow and report where it got to -- without the gate key."""
    found = pipeline_spec.resolve_spec_path(flow)
    target = str(found) if found else None
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
        filed = await _refile_gate(res, flow)
        if filed is None:
            out["note"] = (
                "This run is paused at a gate. The decision has been placed in "
                "the human's inbox. You cannot open it; say that it is waiting."
            )
        else:
            # The run EXISTS and is holding. Saying "the tool failed" here would
            # be false and expensive: the model retries, and a second run does
            # the same GPU work and waits at its own gate (review 2, finding 3).
            out["inbox_error"] = filed
            out["note"] = (
                f"This run is paused at a gate, but it could NOT be put in the "
                f"human's inbox ({filed}). The run itself started and is "
                f"holding as {run_id}. Do NOT start the flow again -- say that "
                f"the run is waiting and that nobody has been notified, and "
                f"give the run id."
            )
    else:
        out["output"] = res.output

    log.info("agent started flow %s -> run %s (paused=%s)", flow, run_id, paused)
    return out


async def _refile_gate(res, flow: str) -> str | None:
    """Put the pending decision in front of the human. None means it landed.

    Without this the run pauses and nobody learns of it: the Pilot files its own
    inbox item only for runs IT started, and this one was started by an agent.
    A failure here is reported into the answer rather than swallowed -- a gate
    nobody can see is worse than a flow that did not start. It used to say that
    and then re-raise, which lost the answer, the run id with it, and had the
    model start the flow a second time (review 2, finding 3). It returns the
    reason instead, and the caller carries it into the answer.
    """
    payload = {
        **res.to_dict(),
        # inbox_refile titles the item from this; without it every agent-started
        # gate would show up as the word "Pipeline".
        "pipeline": flow,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.post(f"{_PILOT_URL}/inbox/refile", json=payload)
        # A 4xx/5xx used to count as success: the item was never filed and the
        # model was told the decision was waiting for someone.
        if r.status_code >= 400:
            log.error("inbox refused the gate for run %s: HTTP %s %s",
                      getattr(res, "run_id", None), r.status_code, r.text[:200])
            return f"the inbox answered HTTP {r.status_code}"
    except Exception as e:
        log.exception("could not file the gate for run %s into the inbox",
                      getattr(res, "run_id", None))
        return f"{type(e).__name__}: {e}"[:200]
    return None


async def _run_status(run_id: str) -> dict:
    # A model composes this argument, so it may be anything. The library refuses
    # an id that cannot name a log file; here that is the same answer as "no
    # such run" -- a tool result, never a 500 the model reads as a broken tool.
    try:
        events = await asyncio.to_thread(
            pipeline_runlog.read_events, os.path.basename(run_id))
    except pipeline_runlog.BadRunId:
        return {"error": f"no run named {run_id!r}"}
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
        return {"error": "Search budget for this turn is used up.",
                "hint": "Do not search further. Write the answer from what you "
                        "have, and say in the report that you stopped for budget "
                        "reasons — that is a valid reason and deserves to be "
                        "named."}
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
        return {"error": "Reading budget for this turn is used up.",
                "hint": "No further pages. Call `notes_review` and write the "
                        "answer from your notes. Say in the report that you "
                        "stopped for budget reasons."}
    urls = urls[:left]
    _SPENT["pages"] += len(urls)
    # The model chooses max_chars, so it may not be a number at all.
    try:
        cap = int(max_chars) if max_chars not in (None, "") else _lim("page_chars")
        if cap <= 0:
            cap = _lim("page_chars")
    except (TypeError, ValueError):
        cap = _lim("page_chars")

    async def one(u: str) -> dict:
        try:
            return await web.fetch(u, max_chars=cap)
        except Exception as e:
            # Deliberately every exception, not web.WebError alone. Measured
            # against httpx 0.28.1: a url carrying a tab raises
            # httpx.InvalidURL, which is NOT an httpx.HTTPError, so web.fetch
            # does not wrap it and one bad address in a batch took the whole
            # call down as a 500 -- after the page budget had been charged,
            # and with the good pages thrown away (review 2, finding 2). The
            # contract this tool promises is that a failed page is reported as
            # failed, and that has to hold for every way a page can fail.
            log.warning("web_read: %s failed: %s: %s", u, type(e).__name__, e)
            return {"url": u, "error": f"{type(e).__name__}: {e}"[:300]}

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
        "next": "Now call `note` for each page read — what it says about the "
                "question and which restriction is attached (date, season, "
                "version, lock, licence) — ALL findings in ONE call, as a "
                "list. Only then read on. Before writing, call "
                "`notes_review`.",
    }


def _record_check(claim: str, src: str, res: str, detail: str = "") -> str:
    """Book one source check, or say why it was refused.

    Shared by `verify` and by a `note` that carries a `result`, so the two
    cannot drift apart: a check is a check whichever door it came through, and
    the provenance rule is the same. Returns "" on success, else the reason.
    """
    if res not in ("confirmed", "contradicted", "not_found"):
        return f"unknown result '{res}'"
    # "not findable" may rest on a page that refused to load; the other two
    # may not -- you cannot confirm from a page you never got.
    allowed = (_read_urls_since(_TURN_T0, ok_only=False)
               if res == "not_found" else _read_urls_since(_TURN_T0))
    if _norm_url(src) not in allowed:
        return ("Source was not fetched with web_read in this turn — "
                "read first, then check.")
    _CHECKS.append((time.time(), _SESSION, {
        "claim": claim[:300], "source": src[:300],
        "result": res, "detail": detail[:300]}))
    return ""


async def _call(name: str, arguments: dict) -> dict:
    # A call can arrive with no turn open: an agent the gateway ran by itself
    # (cron, the CLI, an inbound message), or one abandoned at a timeout whose
    # process is still going. Opening a fresh turn for it keeps its notes and
    # its budget out of the registers of the turn that ran BEFORE it, which is
    # where they used to land.
    if not turn_running():
        begin_turn(None, session="")
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
        # What the same conversation established before this question. Measured:
        # a follow-up arrived with an empty notebook because the window had been
        # restamped, so the second answer was built from memory of the first --
        # the exact distance the notes exist to close.
        earlier = notes_earlier(_SESSION, _TURN_T0)
        alle = notes + earlier
        limits = [n for n in alle if n.get("restriction")]
        if not alle:
            return {"notes": [], "hint": "Nothing noted. If you have read pages, "
                                         "the answer has no foundation."}
        # The open points are COMPUTED here rather than asked for, because a
        # note that names its own gap was measured to be exactly where the
        # answer went wrong -- and the gap was named correctly and then walked
        # past. Naming it is evidently easy; closing it is the step that needs
        # machinery.
        done = checks_since(_TURN_T0) + checks_earlier(_SESSION, _TURN_T0)
        offen = open_notes(alle)
        solo = single_source_notes(alle)
        allein = [n for n in solo["candidates"]
                  if n["claim"][:60] not in {o["claim"][:60] for o in offen}]
        out = {
            "notes": notes,
            "count": len(alle),
            "with_restriction": len(limits),
            "checked": len(done),
            "hint": "Write the answer NOW from these notes. Every restriction "
                    "travels with its claim — a recommendation whose "
                    "restriction was left out is not shorter, it is wrong. "
                    "What is not written here, you have not read.",
        }
        if earlier:
            out["earlier"] = earlier
            out["hint"] = (
                f"{len(earlier)} note(s) come from earlier questions in this "
                "conversation and sit under `earlier` — with their "
                "restrictions. They still hold; you need not read them "
                "again. " + out["hint"]
            )
        if done:
            out["already_checked"] = done
        if solo["one_family"]:
            # Not a list of suspects -- a property of the turn, said once.
            out["source_situation"] = (
                f"All {solo['total']} figures of this turn come from one source "
                "family; none is backed by an independent provider. That is "
                "fine for a vendor statement and not for an assessment."
            )
        if allein:
            # Weaker than `offen` on purpose, and labelled as such: standing
            # alone is not being wrong. It is offered because the alternative --
            # asking which facts are load-bearing -- was measured returning the
            # facts the model was already sure of.
            out["single_source"] = allein
            out["hint"] = (
                f"{len(allein)} claim(s) with a figure rest on ONE source, with "
                "no second one backing them. If the recommendation depends "
                "on it, that is the candidate for `verify` — exactly in this "
                "class an error of one version slipped through last time. "
                + out["hint"]
            )
        if offen:
            out["open"] = offen
            # Two outcomes, both complete. Turning every open point into a duty
            # lengthens the chain, and long chains were measured ending with no
            # answer at all -- so saying "unresolved" out loud is a full result
            # here, not the lesser one.
            out["hint"] = (
                f"{len(offen)} point(s) below are OPEN — the note itself says "
                "the figure is not backed. Exactly this has already, "
                "measurably, sunk a recommendation. Two outcomes are "
                "allowed, a third is not: (a) look at the primary source "
                "(web_read) and record the result with `verify`, or (b) "
                "declare it open in the report, explicitly. Passing over it "
                "in silence is the error. "
                + out["hint"]
            )
        return out

    if name == "verify":
        raw = arguments.get("checks")
        if not isinstance(raw, list):
            raw = [arguments] if arguments.get("claim") else []
        # A check is PERFORMED, not asserted. The same record that catches an
        # invented citation decides here whether a check happened at all: a
        # source that was never fetched this turn cannot have confirmed
        # anything. Without this, `verify` would be one more sentence the model
        # can produce in the right shape, which is the failure it exists to fix.
        kept, rejected = [], []
        for item in raw:
            if not isinstance(item, dict):
                continue
            claim = _text(item, "claim")
            src = _text(item, "source")
            res = _text(item, "result").lower()
            if not claim or not src:
                continue
            why = _record_check(claim, src, res, _text(item, "detail"))
            if why:
                rejected.append({"claim": claim[:120], "reason": why})
            else:
                kept.append({"claim": claim[:300], "source": src[:300],
                             "result": res})
        if not kept and not rejected:
            return {"error": "verify needs a 'checks' list, each with claim, "
                             "source and result"}
        out = {"ok": bool(kept), "checked": len(kept),
               "total_this_turn": len(checks_since(_TURN_T0))}
        if rejected:
            out["rejected"] = rejected
            out["hint"] = ("Rejected checks do not count. Fetch the page with "
                           "web_read and check again — or declare the point "
                           "open in the report.")
        else:
            out["hint"] = ("Recorded. What is written here appears next to "
                           "your answer — with its result.")
        return out
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
        kept, checked, refused = [], [], []
        for item in raw:
            if not isinstance(item, dict):
                continue
            claim = _text(item, "claim")
            if not claim:
                continue
            src = _text(item, "source")[:300]
            note = {
                "claim": claim[:400],
                "source": src,
                "restriction": _text(item, "restriction")[:300],
            }
            _NOTES.append((time.time(), _SESSION, note))
            kept.append(note)
            # A note that says what the page DID with the figure is also a
            # source check. Measured across three local turns: the same four
            # tools every time -- search, read, note, notes_review -- and never
            # a fifth, with `verify` allowed, described, and re-described with a
            # concrete trigger in between. It was not the wording. So the record
            # is attached to the act that reliably happens instead of being
            # asked for as an act of its own.
            res = (item.get("result") or "").strip().lower()
            if res:
                why = _record_check(claim, src, res,
                                    (item.get("detail") or "").strip())
                (checked if not why else refused).append(
                    {"claim": claim[:120], **({"reason": why} if why else
                                              {"result": res})})
        if not kept:
            return {"error": "note needs a 'notes' list, each with a claim"}
        out = {"ok": True, "noted": len(kept),
               "notes_so_far": len(notes_since(_TURN_T0)),
               "hint": "Read on, or go straight to the conclusion. Immediately "
                       "BEFORE writing, call `notes_review` and build the answer "
                       "from it."}
        if checked:
            out["checked"] = len(checked)
            out["hint"] = (f"{len(checked)} of them recorded as source checks "
                           "— shown next to your answer. "
                           + out["hint"])
        if refused:
            out["check_rejected"] = refused
            out["hint"] = ("The note stands, the check does not: " + out["hint"])
        return out
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
        # Each element gets the same guard the single-message branch has below:
        # one scalar in a batch used to take the valid messages beside it down
        # with a 500 (review 2, finding 7).
        out = [r for r in [await _dispatch(m if isinstance(m, dict) else {}) for m in msg]
               if r is not None]
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
