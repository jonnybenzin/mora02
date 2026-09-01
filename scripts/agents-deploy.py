#!/usr/bin/env python3
"""Render the agent roster from the repo into the OpenClaw volume.

Pillar 2 of the agent-layer plan: the volume is an impression, not a source.
Config entries and workspace files are rendered INTO it from ``agents/``; throw
the volume away, run this, and the agents are back. Modelled on ``install.sh``
from the mora02-host repo, including its most useful habit -- a ``--check``
that reports drift and changes nothing.

The roster is READ BY LOOKING. One folder under ``agents/instances/`` is one
agent and its folder name is its id::

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

    python3 scripts/agents-deploy.py --check     what would change (exit 1 if any)
    python3 scripts/agents-deploy.py             apply it
    python3 scripts/agents-deploy.py --agent researcher

Everything goes through ``docker exec`` into the gateway container, the path
Phase 0 measured as reachable (P9). Two mechanisms do the writing:

  * ``openclaw config patch --stdin`` -- validated, and it has a ``--dry-run``
    that is exactly the check this script needs. Note that it MERGES objects but
    REPLACES arrays: ``agents.list`` cannot be patched one entry at a time, so
    the whole list is always rendered, main included.
  * ``openclaw agents add|delete`` for the agent directories themselves, and a
    heredoc through ``sh -c`` for the workspace files, which are root-owned
    inside the volume.

WHY main IS IN THE ROSTER. An MCP server is registered globally. Measured on
2026-09-01: a server projected with ``codex.agents: ["researcher"]`` still
reached ``main``, and the only guard that held was an explicit per-agent
``tools.allow``. An agent without one gets everything. So every agent gets one.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
AGENTS_DIR = REPO / "agents"
INSTANCES_DIR = AGENTS_DIR / "instances"
SKILLS_DIR = AGENTS_DIR / "skills"
MCP_FILE = AGENTS_DIR / "mcp.json"
HOUSE_RULES = AGENTS_DIR / "AGENTS.md"

OC = os.environ.get("MORA02_OPENCLAW_CONTAINER", "mora02-openclaw")
DOCKER = os.environ.get("MORA02_DOCKER_BIN", "docker")

# Workspace files an agent may carry in its own folder. Only these are rendered:
# a stray file in an instance directory should not silently become part of a
# prompt. AGENTS.md is deliberately NOT in this list -- the house rules are
# shared and come from agents/AGENTS.md, the same text for every agent.
WORKSPACE_FILES = ["SOUL.md", "TOOLS.md", "USER.md", "IDENTITY.md"]

# Where an agent's workspace lands inside the gateway container, unless the
# instance names its own. Derived from the id, so a new folder is a new agent
# and nothing else has to be written down.
def default_workspace(agent_id: str) -> str:
    return f"/data/openclaw/agents/{agent_id}/workspace"


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
    # would be against a guess, and --check would report confident nonsense.
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


# ---------------------------------------------------------------------------
# what the repo says the world should look like
# ---------------------------------------------------------------------------

def load_roster() -> dict:
    """Read the roster by LOOKING, not by consulting a list of names.

    One folder under agents/instances/ is one agent, and its folder name is its
    id. That is the whole point of increment 3: a new agent comes into being by
    being written down somewhere, and nothing else has to be edited to admit it
    -- no list, no registry, no line of code. The Pilot builder therefore only
    ever has to create a directory.

    The earlier form enumerated agents in a single file because skills/ sat as a
    sibling of the agent folders and a scan could not tell them apart. The
    instances/ level removes that ambiguity, and with it the list.
    """
    if not INSTANCES_DIR.is_dir():
        raise DeployError(f"no instance directory at {INSTANCES_DIR}")

    agents: list[dict] = []
    for folder in sorted(INSTANCES_DIR.iterdir()):
        if not folder.is_dir() or folder.name.startswith("."):
            continue
        manifest = folder / "agent.json"
        if not manifest.is_file():
            # Named rather than skipped: a folder without a manifest is far more
            # likely a half-finished agent than a deliberate placeholder, and a
            # silently ignored agent is the failure this layer keeps guarding
            # against.
            raise DeployError(
                f"{folder.relative_to(REPO)} has no agent.json — an instance "
                f"folder without one cannot be deployed. Remove the folder or "
                f"give it a manifest."
            )
        try:
            agent = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise DeployError(f"cannot read {manifest.relative_to(REPO)}: {e}") from e

        # The id is the folder name, never a field. Two sources for one identity
        # is one source too many, and a manifest whose id disagrees with its
        # folder is a bug waiting for someone to rename one of them.
        agent["id"] = folder.name
        agent.setdefault("workspace", default_workspace(folder.name))
        agent.setdefault("manage_workspace", True)
        agent["_dir"] = str(folder)
        agents.append(agent)

    if not agents:
        raise DeployError(f"no agents found under {INSTANCES_DIR}")

    mcp: dict = {}
    if MCP_FILE.is_file():
        try:
            mcp = json.loads(MCP_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise DeployError(f"cannot read {MCP_FILE.name}: {e}") from e

    return {"agents": agents, "mcp": mcp}


def strip_comments(obj):
    if isinstance(obj, dict):
        return {k: strip_comments(v) for k, v in obj.items() if not k.startswith("_")}
    if isinstance(obj, list):
        return [strip_comments(v) for v in obj]
    return obj


# The written opt-out. An agent may be unrestricted, but only if somebody typed
# the word -- the same shape as .boundaryignore beside the boundary guard: the
# exception is allowed and on the record, the oversight is not.
UNRESTRICTED = "unrestricted"


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
    # active and sort_order belong to the Pilot's view of an agent, not to the
    # gateway's -- they travel to the UI over /agents/roster instead.
    for key in ("name", "workspace", "agentDir", "model", "skills", "tools"):
        if key in agent:
            entry[key] = agent[key]
    # "unrestricted" is our vocabulary, not the gateway's. Leaving the key out
    # is how the gateway is told "no restriction" -- so the marker is dropped
    # here rather than sent, and an agent that once had a list gets it removed.
    if entry.get("tools") == UNRESTRICTED:
        entry["tools"] = None
    return strip_comments(entry)


def desired_workspace_files(agent: dict) -> dict[str, str]:
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
    if HOUSE_RULES.is_file():
        out[f"{ws}/AGENTS.md"] = HOUSE_RULES.read_text(encoding="utf-8")

    for name in WORKSPACE_FILES:
        p = src / name
        if p.is_file():
            out[f"{ws}/{name}"] = p.read_text(encoding="utf-8")
    for skill in agent.get("skills", []):
        folder = SKILLS_DIR / skill
        sp = folder / "SKILL.md"
        if not sp.is_file():
            raise DeployError(
                f"agent {agent['id']!r} wants skill {skill!r}, but "
                f"{sp.relative_to(REPO)} does not exist"
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

def plan(roster: dict, only: str | None) -> tuple[list[str], dict, dict]:
    """Work out the difference without touching anything.

    Returns (human-readable drift lines, the agents.list to write, the files
    to write). An empty drift list means the volume already matches the repo.
    """
    config = read_config()
    live_agents = {a.get("id"): a for a in (config.get("agents") or {}).get("list") or []}
    live_mcp = (config.get("mcp") or {}).get("servers") or {}

    drift: list[str] = []
    agents = [a for a in roster["agents"] if only is None or a["id"] == only]
    if only and not agents:
        raise DeployError(f"no agent {only!r} in {ROSTER.name}")

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

    for stray in live_agents:
        if stray not in {a["id"] for a in roster["agents"]}:
            # Reported, never removed. An agent that someone made by hand is a
            # fact about this machine, and deleting it would prune its sessions.
            drift.append(f"agent/{stray}: exists in the gateway but not in the roster (left alone)")
            rendered.append(live_agents[stray])

    # --- the workspace files ----------------------------------------------
    # Only files that actually differ go into the write set. Writing the
    # unchanged ones too is harmless but dishonest: the run then prints
    # "writing X" for a file it did not change, and a log that says more than it
    # did is a log nobody can use to tell a real change from a no-op.
    files: dict[str, str] = {}
    for a in agents:
        for path, body in desired_workspace_files(a).items():
            have = remote_file(path)
            if have is None:
                drift.append(f"file/{path}: missing")
                files[path] = body
            elif have != body:
                drift.append(f"file/{path}: differs ({digest(have)} -> {digest(body)})")
                files[path] = body

    return drift, {"list": rendered}, files


def apply(roster: dict, agents_block: dict, files: dict[str, str], only: str | None) -> None:
    # 1. the agents themselves must exist before a config entry can name them
    rc, out = docker("openclaw", "agents", "list")
    existing = out if rc == 0 else ""
    for a in roster["agents"]:
        if only is not None and a["id"] != only:
            continue
        if a["id"] == "main" or f"- {a['id']}" in existing:
            continue
        print(f"  creating agent {a['id']}")
        # --non-interactive is not optional: without it `agents add` PROMPTS for
        # the workspace and this script would hang with no output (measured in
        # phase 0). The name is positional; there is no --id.
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
        print(f"  writing {path}")
        write_remote(path, body)

    # 3. the MCP servers
    for name, want in strip_comments(roster.get("mcp") or {}).items():
        print(f"  registering mcp/{name}")
        # `mcp set` rather than `mcp add`: add refuses a name that already
        # exists, which would make a second run of this script an error rather
        # than a no-op.
        rc, out = docker("openclaw", "mcp", "set", name, json.dumps(want))
        if rc != 0:
            raise DeployError(f"could not register mcp/{name}: {out.strip()[:300]}")

    # 4. the config, in one validated write
    print("  patching agents.list")
    rc, out = docker(
        "openclaw", "config", "patch", "--stdin",
        stdin=json.dumps({"agents": agents_block}),
    )
    if rc != 0:
        raise DeployError(f"config patch failed: {out.strip()[:400]}")
    print("   ", out.strip().splitlines()[-1] if out.strip() else "ok")

    # 5. drop cached MCP runtimes so the next turn sees the new server. Cheap,
    #    and skipping it is a plausible reason for a tool to be "missing" right
    #    after a rollout.
    docker("openclaw", "mcp", "reload")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true",
                    help="report drift and change nothing (exit 1 if there is any)")
    ap.add_argument("--agent", help="only this agent (the config list is still written whole)")
    args = ap.parse_args()

    try:
        roster = load_roster()
        # Before anything is read from the gateway: a roster that leaves a tool
        # surface unsaid is refused, --check included. Checking a roster that
        # cannot be applied would report drift nobody may close.
        check_tools(roster)
        drift, agents_block, files = plan(roster, args.agent)
    except DeployError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if args.check:
        if not drift:
            print("in sync — the volume matches the repo")
            return 0
        print(f"{len(drift)} difference(s):")
        for line in drift:
            print("  " + line)
        return 1

    if not drift:
        print("nothing to do — already in sync")
        return 0

    print(f"{len(drift)} difference(s) to close:")
    for line in drift:
        print("  " + line)
    print()
    try:
        apply(roster, agents_block, files, args.agent)
    except DeployError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    # Say whether it actually took, rather than assuming the writes landed.
    try:
        left, _, _ = plan(roster, args.agent)
    except DeployError as e:
        print(f"applied, but could not verify: {e}", file=sys.stderr)
        return 2
    left = [d for d in left if "left alone" not in d]
    if left:
        print("\nstill different after applying:")
        for line in left:
            print("  " + line)
        return 1
    print("\ndone — in sync")
    return 0


if __name__ == "__main__":
    sys.exit(main())
