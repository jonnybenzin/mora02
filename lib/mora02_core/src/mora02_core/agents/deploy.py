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

The roster is READ BY LOOKING. One folder under ``instances/`` is one agent and
its folder name is its id::

    agents/
      AGENTS.md                     house rules, rendered into every workspace
      mcp.json                      the servers to register
      skills/<name>/SKILL.md        skills, granted per agent
      instances/<id>/agent.json     one agent
      instances/<id>/SOUL.md        its personality, prose in a prose file

Nothing enumerates the agents, so creating one means creating a directory and
nothing else -- which is what lets a builder in the browser make one without a
line of code changing. The plan had this data in Baserow; files won because the
reason for Baserow was the free CRUD frontend, and increment 4 builds a frontend
regardless. Files also answer the risk the plan itself named: a prompt in a
database cell has no history, a prompt in a file has git.

Everything goes through ``docker exec`` into the gateway container, the path
Phase 0 measured as reachable (P9). Two mechanisms do the writing:

  * ``openclaw config patch --stdin`` -- validated, and it has a ``--dry-run``
    that is exactly the check this module needs. Note that it MERGES objects but
    REPLACES arrays: ``agents.list`` cannot be patched one entry at a time, so
    the whole list is always rendered, main included.
  * ``openclaw agents add|delete`` for the agent directories themselves, and
    ``cat`` through ``sh -c`` for the workspace files, which are root-owned
    inside the volume.

WHY main IS IN THE ROSTER. An MCP server is registered globally. Measured on
2026-09-01: a server projected with ``codex.agents: ["researcher"]`` still
reached ``main``, and the only guard that held was an explicit per-agent
``tools.allow``. An agent without one gets everything. So every agent gets one.

Environment:
  MORA02_AGENTS_DIR          the ``agents/`` folder; default is the repo's when
                             run from a checkout, ``/data/agents`` in a container
  MORA02_OPENCLAW_CONTAINER  gateway container, default ``mora02-openclaw``
  MORA02_DOCKER_BIN          docker binary, default ``docker``
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Callable

from mora02_core.agents.store import (
    AGENTS_DIR as _STORE_DIR,
    StoreError,
    load_roster,
)

OC = os.environ.get("MORA02_OPENCLAW_CONTAINER", "mora02-openclaw")
DOCKER = os.environ.get("MORA02_DOCKER_BIN", "docker")

# Workspace files an agent may carry in its own folder. Only these are rendered:
# a stray file in an instance directory should not silently become part of a
# prompt. AGENTS.md is deliberately NOT in this list -- the house rules are
# shared and come from agents/AGENTS.md, the same text for every agent.
WORKSPACE_FILES = ["SOUL.md", "TOOLS.md", "USER.md", "IDENTITY.md"]

# The written opt-out. An agent may be unrestricted, but only if somebody typed
# the word -- the same shape as .boundaryignore beside the boundary guard: the
# exception is allowed and on the record, the oversight is not.
UNRESTRICTED = "unrestricted"


class DeployError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# talking to the container
# ---------------------------------------------------------------------------

def docker(*argv: str, stdin: str | None = None) -> tuple[int, str]:
    proc = subprocess.run(
        [DOCKER, "exec", "-i", OC, *argv],
        input=stdin, capture_output=True, text=True,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _config_key(key: str) -> dict:
    """One config subtree, or {} if the gateway does not carry that key yet.

    Fetched key by key rather than as one whole document: `config get` with no
    key is the guided-setup entry point, and a section that has never been
    written (mcp, before the first rollout) is a normal state, not an error.
    """
    rc, out = docker("openclaw", "config", "get", key, "--json")
    if rc != 0:
        return {}
    try:
        return json.loads(out[out.index("{"):]) or {}
    except (ValueError, IndexError):
        return {}


def read_config() -> dict:
    # A failure to read `agents` IS fatal: without it every comparison below
    # would be against a guess, and a check would report confident nonsense.
    rc, out = docker("openclaw", "config", "get", "agents", "--json")
    if rc != 0:
        raise DeployError(f"could not read the gateway config: {out.strip()[:300]}")
    return {"agents": _config_key("agents"), "mcp": _config_key("mcp")}


def remote_file(path: str) -> str | None:
    rc, out = docker("sh", "-c", f"cat {path} 2>/dev/null")
    return out if rc == 0 and out else None


def write_remote(path: str, body: str) -> None:
    """Write one file inside the container, contents passed on stdin.

    Not a heredoc: a marker inside the body would end it early, and these are
    Markdown files that may legitimately contain anything.
    """
    rc, out = docker(
        "sh", "-c", f"mkdir -p $(dirname {path}) && cat > {path}", stdin=body,
    )
    if rc != 0:
        raise DeployError(f"could not write {path}: {out.strip()[:200]}")


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
    for agent in roster.get("agents", []):
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


def desired_workspace_files(agent: dict, agents_dir: Path) -> dict[str, str]:
    """{container path: contents} for the files this agent's workspace carries."""
    if not agent.get("manage_workspace"):
        return {}
    src = Path(agent["_dir"])
    ws = agent["workspace"]
    out: dict[str, str] = {}

    # The house rules are shared, not per-agent. agents/AGENTS.md carries no
    # instance's name -- every one of its rules exists because a model was
    # measured breaking it, and they apply to whoever holds the tools. Rendering
    # the same text into every workspace is how "these apply to all of you"
    # stops being a claim.
    house_rules = agents_dir / "AGENTS.md"
    if house_rules.is_file():
        out[f"{ws}/AGENTS.md"] = house_rules.read_text(encoding="utf-8")

    for name in WORKSPACE_FILES:
        p = src / name
        if p.is_file():  # follows a symlink: a shared SOUL.md renders as text
            out[f"{ws}/{name}"] = p.read_text(encoding="utf-8")
    for skill in agent.get("skills", []):
        folder = agents_dir / "skills" / skill
        sp = folder / "SKILL.md"
        if not sp.is_file():
            raise DeployError(
                f"agent {agent['id']!r} wants skill {skill!r}, but "
                f"skills/{skill}/SKILL.md does not exist"
            )
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


# ---------------------------------------------------------------------------
# comparing, and closing the gap
# ---------------------------------------------------------------------------

def plan(roster: dict, only: str | None, agents_dir: Path) -> tuple[list[str], dict, dict, list[str]]:
    """Work out the difference without touching anything.

    Returns (human-readable drift lines, the agents.list to write, the files
    to write, gateway agents to delete). An empty drift list means the volume
    already matches the repo.
    """
    config = read_config()
    live_agents = {a.get("id"): a for a in (config.get("agents") or {}).get("list") or []}
    live_mcp = (config.get("mcp") or {}).get("servers") or {}

    drift: list[str] = []
    agents = [a for a in roster["agents"] if only is None or a["id"] == only]
    if only and not agents:
        raise DeployError(f"no agent {only!r} under {agents_dir / 'instances'}")

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
    rendered: list[dict] = []
    for a in roster["agents"]:
        want = desired_agent_entry(a)
        have = live_agents.get(a["id"])
        if have is None:
            if only is None or a["id"] == only:
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
    trashed = trashed_ids(agents_dir)
    remove: list[str] = []
    wanted = {a["id"] for a in roster["agents"]}
    for stray in live_agents:
        if stray in wanted:
            continue
        if stray in trashed:
            drift.append(f"agent/{stray}: deleted in the roster, still in the gateway")
            remove.append(stray)
        else:
            drift.append(f"agent/{stray}: exists in the gateway but not in the roster (left alone)")
            rendered.append(live_agents[stray])

    # --- the workspace files ----------------------------------------------
    # Only files that actually differ go into the write set. Writing the
    # unchanged ones too is harmless but dishonest: the run then prints
    # "writing X" for a file it did not change, and a log that says more than it
    # did is a log nobody can use to tell a real change from a no-op.
    files: dict[str, str] = {}
    for a in agents:
        for path, body in desired_workspace_files(a, agents_dir).items():
            have = remote_file(path)
            if have is None:
                drift.append(f"file/{path}: missing")
                files[path] = body
            elif have != body:
                drift.append(f"file/{path}: differs ({digest(have)} -> {digest(body)})")
                files[path] = body

    return drift, {"list": rendered}, files, remove


def trashed_ids(agents_dir: Path) -> set[str]:
    """Ids of agents the builder deleted: folders under instances/.trash/.

    A trashed folder is named ``<id>-<stamp>`` so two deletions of the same id
    can coexist; the id is everything before the last ``-<14 digits>``.
    """
    trash = agents_dir / "instances" / ".trash"
    if not trash.is_dir():
        return set()
    ids: set[str] = set()
    for f in trash.iterdir():
        if not f.is_dir():
            continue
        head, _, tail = f.name.rpartition("-")
        ids.add(head if head and tail.isdigit() and len(tail) == 14 else f.name)
    return ids


def apply(roster: dict, agents_block: dict, files: dict[str, str],
          remove: list[str], only: str | None, say: Callable[[str], None]) -> None:
    # 1. the agents themselves must exist before a config entry can name them
    existing = gateway_agent_ids()
    for a in roster["agents"]:
        if only is not None and a["id"] != only:
            continue
        if a["id"] == "main" or a["id"] in existing:
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
            raise DeployError(f"could not create {a['id']}: {out.strip()[:300]}")

    # 2. the workspace files, before the config that grants the skills -- an
    #    allow-listed skill whose file is not there yet is an avoidable warning
    for path, body in files.items():
        say(f"writing {path}")
        write_remote(path, body)

    # 3. the MCP servers
    for name, want in strip_comments(roster.get("mcp") or {}).items():
        say(f"registering mcp/{name}")
        # `mcp set` rather than `mcp add`: add refuses a name that already
        # exists, which would make a second run an error rather than a no-op.
        rc, out = docker("openclaw", "mcp", "set", name, json.dumps(want))
        if rc != 0:
            raise DeployError(f"could not register mcp/{name}: {out.strip()[:300]}")

    # 4. agents deleted in the builder -- BEFORE the config write. Measured on
    #    the first live T10 (2026-09-02): with the list already patched without
    #    the agent, `agents delete` answered "unknown agent id" -- the gateway
    #    had already forgotten the name it was asked to remove, and its
    #    directory and bindings stayed behind. Deleting first lets the gateway
    #    take its own entry, bindings and directory out (P10), and the patch
    #    that follows merely confirms a list that no longer names it.
    #    `--force` because the question it would ask has been answered in the
    #    browser already.
    for aid in remove:
        say(f"deleting agent {aid} from the gateway")
        rc, out = docker("openclaw", "agents", "delete", aid, "--force", "--json")
        if rc != 0:
            raise DeployError(f"could not delete {aid}: {out.strip()[:300]}")

    # 5. the config, in one validated write
    say("patching agents.list")
    rc, out = docker(
        "openclaw", "config", "patch", "--stdin",
        stdin=json.dumps({"agents": agents_block}),
    )
    if rc != 0:
        raise DeployError(f"config patch failed: {out.strip()[:400]}")

    # 6. drop cached MCP runtimes so the next turn sees the new server. Cheap,
    #    and skipping it is a plausible reason for a tool to be "missing" right
    #    after a rollout.
    docker("openclaw", "mcp", "reload")


# ---------------------------------------------------------------------------
# the one entry point both doors use
# ---------------------------------------------------------------------------

def run(*, check: bool = False, only: str | None = None,
        agents_dir: Path | None = None,
        say: Callable[[str], None] | None = None) -> dict:
    """Check or apply, and say what happened in a shape both a shell and a
    browser can show.

    Returns::

        {"ok": bool, "in_sync": bool, "applied": bool,
         "drift": [...], "left": [...], "log": [...], "error": str|None}

    ``drift`` is what differed before; ``left`` is what still differs after an
    apply (empty when it took). Raises nothing: an error is a field, so the
    HTTP layer can turn it into a status code and the CLI into an exit code
    without either re-deriving what went wrong.
    """
    agents_dir = Path(agents_dir or _STORE_DIR)
    log: list[str] = []

    def _say(line: str) -> None:
        log.append(line)
        if say:
            say(line)

    result = {"ok": False, "in_sync": False, "applied": False,
              "drift": [], "left": [], "log": log, "error": None}
    try:
        roster = load_roster(agents_dir)
        # Before anything is read from the gateway: a roster that leaves a tool
        # surface unsaid is refused, check mode included. Checking a roster that
        # cannot be applied would report drift nobody may close.
        check_tools(roster)
        drift, agents_block, files, remove = plan(roster, only, agents_dir)
    except (StoreError, DeployError) as e:
        result["error"] = str(e)
        return result

    result["drift"] = drift
    if not drift:
        result.update(ok=True, in_sync=True)
        return result
    if check:
        result["ok"] = True
        return result

    try:
        apply(roster, agents_block, files, remove, only, _say)
    except DeployError as e:
        result["error"] = str(e)
        return result
    result["applied"] = True

    # Say whether it actually took, rather than assuming the writes landed.
    try:
        left, _, _, _ = plan(roster, only, agents_dir)
    except (StoreError, DeployError) as e:
        result["error"] = f"applied, but could not verify: {e}"
        return result
    left = [d for d in left if "left alone" not in d]
    result["left"] = left
    result["ok"] = not left
    result["in_sync"] = not left
    return result
