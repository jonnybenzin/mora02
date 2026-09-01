#!/usr/bin/env python3
"""Render the agent roster from the repo into the OpenClaw volume.

Pillar 2 of the agent-layer plan: the volume is an impression, not a source.
Config entries and workspace files are rendered INTO it from ``agents/`` and
from ``agents/agents.json``; throw the volume away, run this, and the agents are
back. Modelled on ``install.sh`` from the mora02-host repo, including its most
useful habit -- a ``--check`` that reports drift and changes nothing.

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
ROSTER = REPO / "agents" / "agents.json"
SKILLS_DIR = REPO / "agents" / "skills"

OC = os.environ.get("MORA02_OPENCLAW_CONTAINER", "mora02-openclaw")
DOCKER = os.environ.get("MORA02_DOCKER_BIN", "docker")

# Workspace files an agent may carry. Only these are rendered: a stray file in
# an agent's repo directory should not silently become part of its prompt.
WORKSPACE_FILES = ["SOUL.md", "AGENTS.md", "TOOLS.md", "USER.md", "IDENTITY.md"]


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
    try:
        roster = json.loads(ROSTER.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise DeployError(f"cannot read {ROSTER}: {e}") from e
    # Keys starting with _ are commentary. They are in the file on purpose --
    # a config without its reasons is a config nobody dares change -- but they
    # must never reach the gateway.
    return roster


def strip_comments(obj):
    if isinstance(obj, dict):
        return {k: strip_comments(v) for k, v in obj.items() if not k.startswith("_")}
    if isinstance(obj, list):
        return [strip_comments(v) for v in obj]
    return obj


def desired_agent_entry(agent: dict) -> dict:
    """The config entry for one agent, as the gateway wants it."""
    entry = {"id": agent["id"]}
    for key in ("name", "workspace", "agentDir", "model", "skills", "tools"):
        if key in agent:
            entry[key] = agent[key]
    return strip_comments(entry)


def desired_workspace_files(agent: dict) -> dict[str, str]:
    """{container path: contents} for the files this agent's workspace carries."""
    if not agent.get("manage_workspace"):
        return {}
    src = REPO / agent["files"]
    ws = agent["workspace"]
    out: dict[str, str] = {}
    for name in WORKSPACE_FILES:
        p = src / name
        if p.is_file():
            out[f"{ws}/{name}"] = p.read_text(encoding="utf-8")
    for skill in agent.get("skills", []):
        sp = SKILLS_DIR / skill / "SKILL.md"
        if not sp.is_file():
            raise DeployError(
                f"agent {agent['id']!r} wants skill {skill!r}, but "
                f"{sp.relative_to(REPO)} does not exist"
            )
        out[f"{ws}/skills/{skill}/SKILL.md"] = sp.read_text(encoding="utf-8")
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
    files: dict[str, str] = {}
    for a in agents:
        for path, body in desired_workspace_files(a).items():
            files[path] = body
            have = remote_file(path)
            if have is None:
                drift.append(f"file/{path}: missing")
            elif have != body:
                drift.append(f"file/{path}: differs ({digest(have)} -> {digest(body)})")

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
