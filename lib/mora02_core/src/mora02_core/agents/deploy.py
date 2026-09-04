"""Render the agent roster from ``agents/`` into the OpenClaw volume.

Pillar 2 of the agent-layer plan: the volume is an impression, not a source.
Config entries and workspace files are rendered INTO it from ``agents/``; throw
the volume away, run this, and the agents are back. Modelled on ``install.sh``
from the mora02-host repo, including its most useful habit -- a check mode that
reports drift and changes nothing.

Why this lives in the library and not in ``scripts/agents-deploy.py``: the
script was the only door, and it opens from the host shell. The builder in the
browser needs the same rollout from inside script-runner, which has the docker
CLI and the socket but not ``scripts/``. Two doors, one mechanism -- the same
shape as ``mora02_core.agents.cli`` for a turn. The script is now a wrapper
around :func:`run`.

The roster is READ BY LOOKING. One folder under ``data/agents/instances/`` is
one agent and its folder name is its id::

    agents/                         the platform (public repo)
      AGENTS.md                     house rules, rendered into every workspace
      mcp.json                      the servers to register
      gateway.json                  the reception desk's tool list (main)
      tools.json                    the gateway's tools, described
      skills/<name>/SKILL.md        skills, granted per agent
    data/agents/                    this installation (gitignored)
      USER.md                       the person, rendered into every workspace
      instances/<id>/agent.json     one agent
      instances/<id>/SOUL.md        its personality, prose in a prose file
      skills/<name>/SKILL.md        skills of this machine's own

Nothing enumerates the agents, so creating one means creating a directory and
nothing else -- which is what lets a builder in the browser make one without a
line of code changing. The plan had this data in Baserow; files won because the
reason for Baserow was the free CRUD frontend, and increment 4 builds a frontend
regardless. Files also answer the risk the plan itself named: a prompt in a
database cell has no history, a prompt in a file has git (make data/agents a
private repo).

Everything goes through ``docker exec`` into the gateway container, the path
Phase 0 measured as reachable (P9). Two mechanisms do the writing:

  * ``openclaw config patch --stdin`` -- validated, and it has a ``--dry-run``
    that is exactly the check this module needs. Note that it MERGES objects but
    REPLACES arrays: ``agents.list`` cannot be patched one entry at a time, so
    the whole list is always rendered, main included.
  * ``openclaw agents add|delete`` for the agent directories themselves, and
    ``cat`` through ``sh -c`` for the workspace files, which are root-owned
    inside the volume.

WHY main IS RENDERED TOO. An MCP server is registered globally. Measured on
2026-09-01: a server projected with ``codex.agents: ["researcher"]`` still
reached ``main``, and the only guard that held was an explicit per-agent
``tools.allow``. An agent without one gets everything. ``main`` is not an
agent anybody made -- it is the gateway's reception desk -- so its list is
platform configuration (agents/gateway.json), rendered beside the agents
because ``agents.list`` is replaced whole.

Environment:
  MORA02_AGENTS_DIR          the shipped ``agents/`` folder
  MORA02_AGENTS_LOCAL_DIR    this installation's root (the builder's)
  MORA02_OPENCLAW_CONTAINER  gateway container, default ``mora02-openclaw``
  MORA02_DOCKER_BIN          docker binary, default ``docker``
"""

from __future__ import annotations

import hashlib
import json
import os
import posixpath
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from mora02_core.agents.store import (
    WORKSPACE_EXTRA,
    Roots,
    StoreError,
    find_skill,
    is_local_model,
    load_roster,
    local_reasons,
    roots,
    soul_source,
)
from mora02_core.agents.store import LETTERBOX_ID
from mora02_core.agents.cli import first_json_object

OC = os.environ.get("MORA02_OPENCLAW_CONTAINER", "mora02-openclaw")
DOCKER = os.environ.get("MORA02_DOCKER_BIN", "docker")

# The written opt-out. An agent may be unrestricted, but only if somebody typed
# the word -- the same shape as .boundaryignore beside the boundary guard: the
# exception is allowed and on the record, the oversight is not.
UNRESTRICTED = "unrestricted"


class DeployError(RuntimeError):
    pass


class GatewayError(DeployError):
    """The gateway could not be reached or refused a command.

    Separated from the roster's own problems because the two need different
    answers: a manifest nobody can deploy is the person's to fix, a container
    that is down is not, and the builder showed "roster validation failed" for
    a stopped gateway (review 2, finding 5).
    """


# ---------------------------------------------------------------------------
# talking to the container
# ---------------------------------------------------------------------------

def docker(*argv: str, stdin: str | None = None) -> tuple[int, str]:
    proc = subprocess.run(
        [DOCKER, "exec", "-i", OC, *argv],
        input=stdin, capture_output=True, text=True,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _config_key(key: str, *, required: bool = False) -> dict:
    """One config subtree, or {} if the gateway does not carry that key yet.

    Fetched key by key rather than as one whole document: `config get` with no
    key is the guided-setup entry point, and a section that has never been
    written (mcp, before the first rollout) is a normal state, not an error.
    ``required`` makes that state fatal instead -- without `agents` every
    comparison would be against a guess, and a check would report confident
    nonsense.

    An answer that CARRIES an object which cannot be read is always fatal.
    Before review finding A2 (2026-09-03) the reader sliced from the first
    brace and turned any parse error into {}: with the warning line the CLI
    prints after its JSON, every plan was computed against an empty gateway,
    "does not exist" for all, and a rollout that then re-created what was
    already there. An empty gateway is a result; an unreadable one is an error.
    """
    rc, out = docker("openclaw", "config", "get", key, "--json")
    if rc != 0:
        if required:
            raise GatewayError(f"could not read the gateway config: {out.strip()[:300]}")
        return {}
    if "{" not in out:
        # No object at all (a key that reads as null): the same "not written
        # yet" state as a non-zero exit, and treated the same way.
        if required:
            raise GatewayError(f"`config get {key}` carried no object: {out.strip()[:200]}")
        return {}
    data = first_json_object(out, accept=lambda _o: True)
    if data is None:
        raise GatewayError(f"unreadable answer from `config get {key}`: {out.strip()[:200]}")
    return data


def read_config() -> dict:
    return {"agents": _config_key("agents", required=True), "mcp": _config_key("mcp"),
            "models": _config_key("models")}


def remote_file(path: str) -> str | None:
    # Quoted, here and below: a path reaches the shell from a manifest field or
    # a file name in a skill folder. Unquoted, a space breaks the rollout and a
    # crafted value runs as root in the gateway (review finding A1, 2026-09-03).
    rc, out = docker("sh", "-c", f"cat {shlex.quote(path)} 2>/dev/null")
    return out if rc == 0 and out else None


def write_remote(path: str, body: str) -> None:
    """Write one file inside the container, contents passed on stdin.

    Not a heredoc: a marker inside the body would end it early, and these are
    Markdown files that may legitimately contain anything.
    """
    rc, out = docker(
        "sh", "-c",
        f"mkdir -p {shlex.quote(posixpath.dirname(path))} && cat > {shlex.quote(path)}",
        stdin=body,
    )
    if rc != 0:
        raise GatewayError(f"could not write {path}: {out.strip()[:200]}")


def remove_remote(path: str) -> None:
    """Delete one file inside the container, and the empty folders it leaves
    behind (a skill folder whose last file went). `rmdir -p` stops at the
    first folder that is not empty, which the workspace itself never is."""
    # `|| true` on the rmdir alone: a folder that is not empty is the normal
    # case and must not fail the run, but a failing `rm` has to be seen. An
    # `exit 0` at the end of the whole command made the check below dead code
    # and every removal look like it worked.
    rc, out = docker(
        "sh", "-c",
        f"rm -f {shlex.quote(path)} && "
        f"{{ rmdir -p {shlex.quote(posixpath.dirname(path))} 2>/dev/null || true; }}",
    )
    if rc != 0:
        raise GatewayError(f"could not remove {path}: {out.strip()[:200]}")


# The rollout's own record of what it rendered into a workspace, one relative
# path per line. It is what makes removal possible: a file the roster no
# longer renders is only known to be the rollout's -- and not the agent's own,
# or the gateway's -- because this list says so. Nothing outside it is ever
# removed.
RENDERED_RECORD = ".mora02-rendered"


def rendered_record(ws: str, rels: set[str]) -> tuple[str, str]:
    return f"{ws}/{RENDERED_RECORD}", "".join(f"{r}\n" for r in sorted(rels))


def workspace_path(ws: str, rel: str) -> str | None:
    """The full path of a rendered file, or None when ``rel`` does not name one
    inside ``ws``.

    The record is read back out of the agent's OWN workspace, and an agent
    holding ``write`` or ``exec`` can edit it -- as can a prompt-injected turn.
    A line reading ``../../../openclaw.json`` must never become an ``rm -f``
    running as root in the gateway. Quoting (A1) stops a path from becoming a
    command; this stops it from becoming the wrong file.
    """
    if not rel or rel.startswith("/") or ".." in rel.split("/"):
        return None
    full = posixpath.normpath(f"{ws}/{rel}")
    return full if full.startswith(f"{ws}/") else None


def previously_rendered(ws: str) -> set[str] | None:
    """What the last rollout wrote into this workspace, or None when it has
    never written its record (a workspace from before the record existed)."""
    raw = remote_file(f"{ws}/{RENDERED_RECORD}")
    if raw is None:
        return None
    return {ln.strip() for ln in raw.splitlines() if ln.strip()}


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def gateway_agent_ids() -> set[str]:
    rc, out = docker("openclaw", "agents", "list")
    if rc != 0:
        return set()
    return {ln[2:].split(" ")[0].strip() for ln in out.splitlines() if ln.startswith("- ")}


# ---------------------------------------------------------------------------
# what the repo says the world should look like
# ---------------------------------------------------------------------------

def strip_comments(obj):
    if isinstance(obj, dict):
        return {k: strip_comments(v) for k, v in obj.items() if not k.startswith("_")}
    if isinstance(obj, list):
        return [strip_comments(v) for v in obj]
    return obj


def check_tools(roster: dict) -> None:
    """Refuse a roster in which an agent's tool surface is left unsaid.

    An agent without tools.allow does not get FEWER tools, it gets ALL of them --
    every tool the gateway has, plus every MCP tool registered later, without
    anyone touching that agent again. Measured: a server projected at one agent
    still reached the one that had no list. The absent list is therefore not a
    neutral default but the widest possible setting, and it looks like nothing.

    So the rollout refuses rather than quietly rendering it. A warning would not
    do: the atlas drift check spent months proving that a reminder which stops
    nothing stops nothing.
    """
    entries = list(roster.get("agents", []))
    if roster.get("letterbox"):
        entries.append(roster["letterbox"])
    for agent in entries:
        aid = agent.get("id", "<unnamed>")
        tools = agent.get("tools")

        if tools == UNRESTRICTED:
            continue  # said out loud, and it stays in the file to be read

        if not isinstance(tools, dict) or "allow" not in tools:
            raise DeployError(
                f"agent {aid!r} has no tool allow list.\n"
                f"    Without one it receives EVERY tool the gateway has, "
                f"including every MCP tool registered later.\n"
                f"    Set tools.allow, or write  \"tools\": \"{UNRESTRICTED}\"  "
                f"if that is really what is meant."
            )

        allow = tools["allow"]
        if not isinstance(allow, list) or not allow:
            # Not pedantry: the gateway refuses to submit a run that has no
            # callable tool left, so an empty list is a mute agent, not a safe
            # one. The narrowest working setting is one tool, never none.
            raise DeployError(
                f"agent {aid!r} has an empty tool allow list.\n"
                f"    The gateway stops a run that has no callable tool, so this "
                f"agent would not answer at all.\n"
                f"    Name at least one tool."
            )


def check_locality(roster: dict, rt: Roots) -> None:
    """Refuse a roster in which a steering or sensitive agent runs in the cloud.

    ADR-029 point 6 as mechanism. The builder refuses the same thing at the
    form; this is the second door, for a manifest written by hand -- and the
    only door for the reception desk, which has no form. The desk usually
    names no model and runs on whatever the gateway defaults to; that is fine
    while its tools only read, and not a moment longer: a desk that steers
    on an unknown model is the gap the rule exists to close.
    """
    for agent in roster.get("agents", []):
        why = local_reasons(agent, rt)
        if why and not is_local_model(agent.get("model")):
            raise DeployError(
                f"agent {agent.get('id', '<unnamed>')!r} runs on {agent.get('model')!r}, "
                f"which is not local, but it must: " + "; ".join(why) + ".\n"
                f"    Steering and sensitive agents stay in the house (ADR-029)."
            )
    desk = roster.get("letterbox")
    if desk:
        why = local_reasons(desk, rt)
        if why and not desk.get("model"):
            raise DeployError(
                f"the reception desk ({desk.get('id')}) must run locally -- " + "; ".join(why) + " -- "
                f"but names no model of its own, so it runs on whatever the gateway defaults to.\n"
                f"    Give it a local model in agents/gateway.json, or narrow its tool list."
            )
        if why and not is_local_model(desk.get("model")):
            raise DeployError(
                f"the reception desk ({desk.get('id')}) runs on {desk.get('model')!r}, "
                f"which is not local, but it must: " + "; ".join(why) + " (ADR-029)."
            )


def desired_agent_entry(agent: dict) -> dict:
    """The config entry for one agent, as the gateway wants it."""
    entry = {"id": agent["id"]}
    # Only what the gateway knows about. label, icon, colour, description,
    # active, sort_order, timeout and limits belong to the Pilot's view of an
    # agent, not to the gateway's -- they travel to the UI over /agents/roster.
    for key in ("name", "workspace", "agentDir", "model", "skills", "tools"):
        if key in agent:
            entry[key] = agent[key]
    # "unrestricted" is our vocabulary, not the gateway's. Leaving the key out
    # is how the gateway is told "no restriction" -- so the marker is dropped
    # here rather than sent, and an agent that once had a list gets it removed.
    if entry.get("tools") == UNRESTRICTED:
        entry["tools"] = None
    return strip_comments(entry)


def desired_workspace_files(agent: dict, rt: Roots) -> dict[str, str]:
    """{container path: contents} for the files this agent's workspace carries."""
    if not agent.get("manage_workspace"):
        return {}
    src = Path(agent["_dir"])
    ws = agent["workspace"]
    out: dict[str, str] = {}
    agents_dir = rt.platform

    # The house rules are shared, not per-agent. agents/AGENTS.md carries no
    # instance's name -- every one of its rules exists because a model was
    # measured breaking it, and they apply to whoever holds the tools. Rendering
    # the same text into every workspace is how "these apply to all of you"
    # stops being a claim.
    house_rules = agents_dir / "AGENTS.md"
    if house_rules.is_file():
        out[f"{ws}/AGENTS.md"] = house_rules.read_text(encoding="utf-8")

    # The person is shared too, but belongs to the installation, not to the
    # platform: data/agents/USER.md is what every agent knows about whoever it
    # works for -- the standing preference that used to be a "persona" picked
    # per chat (increment 5). It is written by the human and rendered as text;
    # an agent carrying its own USER.md overrides it below, key for key.
    if rt.local is not None:
        person = rt.local / "USER.md"
        if person.is_file():
            out[f"{ws}/USER.md"] = person.read_text(encoding="utf-8")

    # SOUL.md may be the agent's own, a legacy symlink, or borrowed by
    # reference from another agent (possibly in the other root). The store
    # resolves all three; the gateway only ever sees text.
    _, soul_path = soul_source(agent["id"], rt)
    if soul_path is not None:
        out[f"{ws}/SOUL.md"] = soul_path.read_text(encoding="utf-8")
    for name in WORKSPACE_EXTRA:
        p = src / name
        if p.is_file():
            out[f"{ws}/{name}"] = p.read_text(encoding="utf-8")
    for skill in agent.get("skills", []):
        hit = find_skill(skill, rt)
        if hit is None:
            raise DeployError(
                f"agent {agent['id']!r} wants skill {skill!r}, but "
                f"skills/{skill}/SKILL.md does not exist in either root"
            )
        folder = hit[1]
        # The whole folder, not only SKILL.md. A skill may carry material the
        # agent reads at the moment it needs it -- a question catalogue, a
        # template, an example -- and keeping that beside the method is what
        # lets it be improved as prose instead of as code. Only the description
        # of SKILL.md reaches the prompt either way; the rest is read on demand,
        # which is precisely why it may be long.
        for f in sorted(folder.rglob("*")):
            if f.is_file() and not f.name.startswith("."):
                rel = f.relative_to(folder)
                out[f"{ws}/skills/{skill}/{rel}"] = f.read_text(encoding="utf-8")
    return out


# The gateway's marker for a secret it will not print. A catalog rendered from
# a redacted read must not carry the marker as if it were the key.
_REDACTED = "__OPENCLAW_REDACTED__"


def desired_catalog(models_config: dict, existing: dict | None) -> dict:
    """The per-agent model catalog, derived from the gateway's model config.

    Measured 2026-09-02: OpenClaw writes ``<agentDir>/agent/models.json`` once,
    when the agent is created, from the config of that moment -- and never
    again. After the local model's id was renamed and its context window
    raised, every agent still carried the catalog it was born with: main with
    128000 and the old id, recherche with 65536. ``models list`` merged them
    all and offered a model that no longer existed. The catalog is exactly the
    kind of file this rollout exists for: an impression that must follow the
    source, not a source.

    Only what a catalog carries is rendered: providers with baseUrl, api,
    apiKey and models. The apiKey is redacted on read; where the config shows
    the marker, the existing catalog's key is kept (it was written unredacted
    at creation) and otherwise the field is left out rather than filled with
    the marker.
    """
    providers = (models_config or {}).get("providers") or {}
    have = ((existing or {}).get("providers") or {})
    out: dict = {"providers": {}}
    for name, prov in providers.items():
        entry: dict = {}
        for key in ("baseUrl", "api"):
            if key in prov:
                entry[key] = prov[key]
        key = prov.get("apiKey")
        if key and key != _REDACTED:
            entry["apiKey"] = key
        elif have.get(name, {}).get("apiKey"):
            entry["apiKey"] = have[name]["apiKey"]
        entry["models"] = [dict(m) for m in (prov.get("models") or [])]
        out["providers"][name] = entry
    return out


def _agent_dir(entry: dict, live: dict | None) -> str:
    """Where the gateway keeps an agent's own files (not its workspace)."""
    if live and live.get("agentDir"):
        return str(live["agentDir"])
    if entry.get("agentDir"):
        return str(entry["agentDir"])
    return f"/data/openclaw/agents/{entry['id']}/agent"


# ---------------------------------------------------------------------------
# comparing, and closing the gap
# ---------------------------------------------------------------------------

@dataclass
class Plan:
    """What a rollout would do, worked out without touching anything.

    ``drift`` is what differs and would be changed; an empty list means the
    volume already matches the repo. ``notes`` is what was SEEN and is left
    as it is -- a hand-made gateway agent, say. The two used to share one
    list, and a note counted as drift: check mode reported a difference
    forever, apply mode rolled out every time and said ok (review B7,
    2026-09-03).
    """
    drift: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    agents_block: dict = field(default_factory=dict)
    files: dict[str, str] = field(default_factory=dict)
    stale: list[str] = field(default_factory=list)
    remove: list[str] = field(default_factory=list)


def plan(roster: dict, only: str | None, rt: Roots) -> Plan:
    """Work out the difference without touching anything (see Plan)."""
    config = read_config()
    live_agents = {a.get("id"): a for a in (config.get("agents") or {}).get("list") or []}
    live_mcp = (config.get("mcp") or {}).get("servers") or {}

    drift: list[str] = []
    notes: list[str] = []
    trashed = trashed_ids(rt)
    agents = [a for a in roster["agents"] if only is None or a["id"] == only]
    if only and not agents and only not in trashed:
        raise DeployError(f"no agent {only!r} in either root")

    # --- the MCP servers ---------------------------------------------------
    want_mcp = strip_comments(roster.get("mcp") or {})
    for name, want in want_mcp.items():
        have = live_mcp.get(name)
        if have is None:
            drift.append(f"mcp/{name}: not registered")
        else:
            for k, v in want.items():
                if have.get(k) != v:
                    drift.append(f"mcp/{name}.{k}: {have.get(k)!r} -> {v!r}")

    # --- the agent entries -------------------------------------------------
    # The whole list is rendered, not only the agents asked for: config patch
    # replaces arrays wholesale, so writing a subset would delete the rest.
    # The reception desk goes first: it is the gateway's default and the
    # entry every other one is measured against.
    rendered: list[dict] = []
    entries = ([roster["letterbox"]] if roster.get("letterbox") else []) + list(roster["agents"])
    for a in entries:
        want = desired_agent_entry(a)
        have = live_agents.get(a["id"])
        if have is None:
            if only is not None and a["id"] != only:
                # Not this run's agent and not in the gateway yet: it gets no
                # entry either. An entry for an agent `agents add` never made
                # named a directory that did not exist, and since it was then
                # "present", no later rollout created it (review B8).
                continue
            drift.append(f"agent/{a['id']}: does not exist")
            rendered.append(want)
            continue
        # Keep fields the gateway maintains itself (agentDir and friends) that
        # the roster does not speak about, so a rollout never un-sets them.
        merged = {**have, **want}
        rendered.append(merged)
        if only is not None and a["id"] != only:
            continue
        for k, v in want.items():
            if have.get(k) != v:
                drift.append(f"agent/{a['id']}.{k}: {have.get(k)!r} -> {v!r}")

    # --- agents the gateway has and the roster no longer names ------------
    # Two different situations wear the same face. An agent someone made by
    # hand is a fact about this machine and is left alone. An agent the builder
    # moved to instances/.trash/ was deleted ON PURPOSE, and leaving it in the
    # gateway would keep a tool surface alive that nobody can see any more --
    # the exact thing the allow-list discipline exists to prevent. The trash
    # folder is what tells the two apart: it is the written record of intent.
    remove: list[str] = []
    wanted = {a["id"] for a in entries}
    for stray in live_agents:
        if stray in wanted:
            continue
        if only is not None and stray != only:
            # A run for ONE agent touches one agent. Before review B6 the
            # deletions ignored `only`, and `--agent foo` took every trashed
            # agent out of the gateway with it.
            rendered.append(live_agents[stray])
            continue
        if stray in trashed:
            drift.append(f"agent/{stray}: deleted in the roster, still in the gateway")
            remove.append(stray)
        else:
            notes.append(f"agent/{stray}: exists in the gateway but not in the roster (left alone)")
            rendered.append(live_agents[stray])

    # --- the workspace files ----------------------------------------------
    # Only files that actually differ go into the write set. Writing the
    # unchanged ones too is harmless but dishonest: the run then prints
    # "writing X" for a file it did not change, and a log that says more than it
    # did is a log nobody can use to tell a real change from a no-op.
    files: dict[str, str] = {}
    stale: list[str] = []
    for a in agents:
        wanted_files = desired_workspace_files(a, rt)
        for path, body in wanted_files.items():
            have = remote_file(path)
            if have is None:
                drift.append(f"file/{path}: missing")
                files[path] = body
            elif have != body:
                drift.append(f"file/{path}: differs ({digest(have)} -> {digest(body)})")
                files[path] = body
        if not a.get("manage_workspace"):
            continue
        # What the last rollout wrote and this one no longer renders -- a
        # skill taken off the list, a USER.md emptied -- was left in the
        # gateway before, and the agent went on reading a file nobody could
        # see any more (review B9, 2026-09-03). Only files named in the
        # rollout's own record are removed: the agent's and the gateway's
        # files are not the rollout's to take.
        ws = a["workspace"]
        rels = {path[len(ws) + 1:] for path in wanted_files}
        before = previously_rendered(ws)
        for rel in sorted((before or set()) - rels):
            path = workspace_path(ws, rel)
            if path is None:
                # Named, not removed, and the rewrite below drops it: an entry
                # that is not a file in this workspace was not put there by the
                # rollout, and the rollout does not delete what it did not write.
                drift.append(f"record/{a['id']}: entry {rel!r} is not a file in this workspace — ignored")
                continue
            drift.append(f"file/{path}: stale (no longer rendered)")
            stale.append(path)
        if before != rels:
            record_path, record_body = rendered_record(ws, rels)
            if before is None:
                drift.append(f"record/{a['id']}: no record of rendered files yet")
            files[record_path] = record_body

    # --- the per-agent model catalogs --------------------------------------
    # Compared as JSON, not as text: the gateway wrote these with its own key
    # order, and a byte diff would report drift where the content is the same.
    # Rendered for every agent, including one the gateway does not have yet:
    # measured on the first live T6, `agents add` does NOT write a catalog, so
    # skipping the new ones left them "missing" right after the apply.
    models_cfg = config.get("models") or {}
    if models_cfg.get("providers"):
        for a in ([roster["letterbox"]] if roster.get("letterbox") else []) + agents:
            live = live_agents.get(a["id"])
            path = f"{_agent_dir(a, live)}/models.json"
            raw = remote_file(path)
            try:
                existing = json.loads(raw) if raw else None
            except ValueError:
                existing = None
            want = desired_catalog(models_cfg, existing)
            if existing != want:
                what = "missing" if existing is None else "stale (written when the agent was created)"
                drift.append(f"catalog/{a['id']}: {what}")
                files[path] = json.dumps(want, ensure_ascii=False, indent=2) + "\n"

    return Plan(drift=drift, notes=notes, agents_block={"list": rendered},
                files=files, stale=stale, remove=remove)


# Written into a trash folder once the gateway has actually forgotten the
# agent. The folder is the record of intent; the marker is the record that
# the intent was carried out. Without it a trashed id stayed "deleted" for
# ever, and an agent somebody later made by hand under the same name was
# taken out by the next rollout (review B6, 2026-09-03).
TRASH_APPLIED = ".gateway-deleted"


def _trash_folders(rt: Roots, agent_id: str | None = None) -> list[tuple[str, Path]]:
    """(id, folder) for every trashed agent in the installation root. The
    platform root ships no agents (030ad83) and its trash is not read: old
    scratch folders there held ids as deleted for good.

    A trashed folder is named ``<id>-<stamp>`` so two deletions of the same id
    can coexist; the id is everything before the last ``-<14 digits>``.
    """
    out: list[tuple[str, Path]] = []
    trash = rt.local / "instances" / ".trash" if rt.local is not None else None
    if trash is None or not trash.is_dir():
        return out
    for f in sorted(trash.iterdir()):
        if not f.is_dir():
            continue
        head, _, tail = f.name.rpartition("-")
        aid = head if head and tail.isdigit() and len(tail) == 14 else f.name
        if agent_id is None or aid == agent_id:
            out.append((aid, f))
    return out


def trashed_ids(rt: Roots) -> set[str]:
    """Ids the builder deleted and the gateway has not yet been told about."""
    return {aid for aid, f in _trash_folders(rt) if not (f / TRASH_APPLIED).is_file()}


def mark_trash_applied(rt: Roots, agent_id: str) -> None:
    for _, f in _trash_folders(rt, agent_id):
        try:
            (f / TRASH_APPLIED).write_text("deleted from the gateway by the rollout\n", encoding="utf-8")
        except OSError as e:
            raise DeployError(f"deleted {agent_id} from the gateway, but could not record it in {f}: {e}") from e


def apply(roster: dict, p: Plan, only: str | None, rt: Roots,
          say: Callable[[str], None]) -> None:
    # 0. the config write as a dry run, BEFORE anything is created or deleted.
    #    Step 5 is the only step the gateway validates, and step 4 cannot be
    #    undone: a rollout that deleted first and was refused after left the
    #    gateway without the agent while the roster still named it (review
    #    A3, 2026-09-03). The dry run checks the schema, not the outcome
    #    (measured 2026-09-02), which is exactly the part a later step cannot
    #    repair.
    rc, out = docker(
        "openclaw", "config", "patch", "--stdin", "--dry-run",
        stdin=json.dumps({"agents": p.agents_block}),
    )
    if rc != 0:
        raise DeployError(
            f"the gateway refused the agents list before anything was changed "
            f"(dry run): {out.strip()[:400]}"
        )

    # 1. the agents themselves must exist before a config entry can name them
    existing = gateway_agent_ids()
    for a in roster["agents"]:
        if only is not None and a["id"] != only:
            continue
        if a["id"] == LETTERBOX_ID or a["id"] in existing:
            continue
        say(f"creating agent {a['id']}")
        # --non-interactive is not optional: without it `agents add` PROMPTS for
        # the workspace and this would hang with no output (measured in phase
        # 0). The name is positional; there is no --id.
        argv = ["openclaw", "agents", "add", a["id"], "--non-interactive",
                "--workspace", a["workspace"], "--json"]
        if a.get("model"):
            argv += ["--model", a["model"]]
        rc, out = docker(*argv)
        if rc != 0:
            raise GatewayError(f"could not create {a['id']}: {out.strip()[:300]}")

    # 2. the workspace files, before the config that grants the skills -- an
    #    allow-listed skill whose file is not there yet is an avoidable warning
    for path in p.stale:
        say(f"removing {path}")
        remove_remote(path)
    for path, body in p.files.items():
        say(f"writing {path}")
        write_remote(path, body)

    # 3. the MCP servers
    for name, want in strip_comments(roster.get("mcp") or {}).items():
        say(f"registering mcp/{name}")
        # `mcp set` rather than `mcp add`: add refuses a name that already
        # exists, which would make a second run an error rather than a no-op.
        rc, out = docker("openclaw", "mcp", "set", name, json.dumps(want))
        if rc != 0:
            raise GatewayError(f"could not register mcp/{name}: {out.strip()[:300]}")

    # 4. agents deleted in the builder -- BEFORE the config write. Measured on
    #    the first live T10 (2026-09-02): with the list already patched without
    #    the agent, `agents delete` answered "unknown agent id" -- the gateway
    #    had already forgotten the name it was asked to remove, and its
    #    directory and bindings stayed behind. Deleting first lets the gateway
    #    take its own entry, bindings and directory out (P10), and the patch
    #    that follows merely confirms a list that no longer names it.
    #    `--force` because the question it would ask has been answered in the
    #    browser already.
    for aid in p.remove:
        say(f"deleting agent {aid} from the gateway")
        rc, out = docker("openclaw", "agents", "delete", aid, "--force", "--json")
        if rc != 0:
            raise GatewayError(f"could not delete {aid}: {out.strip()[:300]}")
        mark_trash_applied(rt, aid)

    # 5. the config, in one validated write
    say("patching agents.list")
    rc, out = docker(
        "openclaw", "config", "patch", "--stdin",
        stdin=json.dumps({"agents": p.agents_block}),
    )
    if rc != 0:
        raise GatewayError(f"config patch failed: {out.strip()[:400]}")

    # 6. drop cached MCP runtimes so the next turn sees the new server. Cheap,
    #    and skipping it is a plausible reason for a tool to be "missing" right
    #    after a rollout.
    docker("openclaw", "mcp", "reload")


# ---------------------------------------------------------------------------
# the one entry point both doors use
# ---------------------------------------------------------------------------

def run(*, check: bool = False, only: str | None = None,
        rt: Roots | None = None,
        say: Callable[[str], None] | None = None) -> dict:
    """Check or apply, and say what happened in a shape both a shell and a
    browser can show.

    Returns::

        {"ok": bool, "in_sync": bool, "applied": bool, "drift": [...],
         "notes": [...], "left": [...], "log": [...], "error": str|None,
         "error_kind": "gateway"|"roster"|None}

    ``drift`` is what differed before; ``left`` is what still differs after an
    apply (empty when it took); ``notes`` is what was seen and left alone
    (never a reason to apply). Raises nothing: an error is a field, so the
    HTTP layer can turn it into a status code and the CLI into an exit code
    without either re-deriving what went wrong.
    """
    rt = rt if rt is not None else roots()
    log: list[str] = []

    def _say(line: str) -> None:
        log.append(line)
        if say:
            say(line)

    result = {"ok": False, "in_sync": False, "applied": False, "drift": [],
              "notes": [], "left": [], "log": log, "error": None, "error_kind": None}
    try:
        roster = load_roster(rt)
        # An empty roster at THIS door is a missing mount, not an empty house:
        # the platform ships no agents, so the only way to have none is an
        # installation root that is not there (review A4, 2026-09-03 --
        # successor of the "no agents found" guard from 19a6ba0). Checking or
        # applying it would compare the gateway against nothing and call every
        # hand-made agent stray.
        if not roster["agents"]:
            raise DeployError(
                f"no agents found under {rt.local}" if rt.local is not None else
                "no installation root: data/agents/instances is not there, and "
                "MORA02_AGENTS_LOCAL_DIR does not name one either -- nothing to "
                "roll out"
            )
        # Before anything is read from the gateway: a roster that leaves a tool
        # surface unsaid is refused, check mode included. Checking a roster that
        # cannot be applied would report drift nobody may close.
        check_tools(roster)
        check_locality(roster, rt)
        p = plan(roster, only, rt)
    except (StoreError, DeployError) as e:
        result["error"] = str(e)
        result["error_kind"] = "gateway" if isinstance(e, GatewayError) else "roster"
        return result

    result["drift"] = p.drift
    result["notes"] = p.notes
    if not p.drift:
        result.update(ok=True, in_sync=True)
        return result
    if check:
        result["ok"] = True
        return result

    try:
        apply(roster, p, only, rt, _say)
    except DeployError as e:
        result["error"] = str(e)
        result["error_kind"] = "gateway" if isinstance(e, GatewayError) else "roster"
        return result
    result["applied"] = True

    # Say whether it actually took, rather than assuming the writes landed.
    try:
        left = plan(roster, only, rt).drift
    except (StoreError, DeployError) as e:
        result["error"] = f"applied, but could not verify: {e}"
        result["error_kind"] = "gateway" if isinstance(e, GatewayError) else "roster"
        return result
    result["left"] = left
    result["ok"] = not left
    result["in_sync"] = not left
    return result
