"""The agent roster as files: reading it by looking, and writing it back.

One folder under ``data/agents/instances/`` is one agent; its folder name is
its id. This module is the only place that knows the folder layout, so the
rollout (:mod:`mora02_core.agents.deploy`), the HTTP layer in script-runner and
the tests all read and write the same shape without each carrying a copy of it.

WHAT IS PLATFORM AND WHAT IS CONTENT. Two roots with different jobs:

    agents/         the PLATFORM's: skills (how mora02 works), tools.json,
                    mcp.json, AGENTS.md (house rules) and gateway.json (the
                    reception desk, see below). In the public repo, changed
                    through git. Ships NO agents.
    data/agents/    this INSTALLATION's: every agent, and any skill of its own.
                    Gitignored; content of this machine, never of the platform.
                    Make it a private git repo of its own for history.

There is one kind of agent, and it lives in one place. The first builder
session had shipped agents in the repo beside the platform, then two roots for
agents, then two labels in the UI -- and the person asked what the second kind
was for. Nothing: a storage location is not a property of an agent. So the
agents moved out of the repo entirely. What stayed is what a fresh clone
needs -- the methods, the builder, and a tamed reception desk.

THE RECEPTION DESK. ``agents/gateway.json`` describes ``main``, the gateway's
own default agent that an inbound Signal message lands on. Nobody authored it
and nobody talks to it; it is listed nowhere in the builder. It is in the
rollout for one reason: an agent WITHOUT an explicit tool allow list gets every
tool the gateway has (measured 2026-09-01), so its list is platform
configuration, rendered into ``agents.list`` beside the real agents. The id
``main`` is reserved and refused for agents.

What an instance folder holds::

    data/agents/instances/<id>/agent.json   the manifest
    data/agents/instances/<id>/SOUL.md      its personality -- or none, when the
                                            manifest says "soul_shared_with"

Three rules enforced here rather than in a UI, because a UI is one door of two:

* **Limits may be borrowed.** ``"limits": {"same_as": "<id>"}`` resolves to the
  other agent's limits at read time. Measured 2026-09-02: six payload values
  that differed between two instances invalidated a whole day's comparison of
  the models behind them. A reference cannot drift; a copy does within a week.
* **A SOUL may be borrowed the same way.** ``"soul_shared_with": "<id>"`` in
  the manifest; the rollout renders the other agent's text. The one symlink
  made before this existed (recherche-plus -> recherche) is still read.
* **Deletion moves, it does not remove.** A deleted instance goes to
  ``instances/.trash/<id>-<stamp>`` -- invisible to roster and rollout (dot
  folder), recoverable by moving it back, and the record the rollout reads to
  know the gateway's copy should go too.

Ownership: script-runner runs as root inside its container, and both roots are
bind mounts of directories a person owns. Every file and folder this module
creates inherits uid, gid and mode from the directory above it.

Environment:
  MORA02_AGENTS_DIR        the platform root; default ``/data/agents`` when that
                           exists (the container mount), else the repo's own
  MORA02_AGENTS_LOCAL_DIR  the installation root; default ``/data/agents-local``
                           when that exists, else ``<repo>/data/agents`` when
                           that exists, else none (then there are no agents
                           and the builder refuses to create one)
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

_REPO = Path(__file__).resolve().parents[5]

LETTERBOX_ID = "main"


def _default_platform() -> Path:
    env = os.environ.get("MORA02_AGENTS_DIR")
    if env:
        return Path(env)
    mount = Path("/data/agents")
    return mount if mount.is_dir() else _REPO / "agents"


def _default_local() -> Path | None:
    env = os.environ.get("MORA02_AGENTS_LOCAL_DIR")
    if env:
        # Only if it exists: the variable names a bind mount, and a mount that
        # is not there must read as "no root" (the 503 the API already gives),
        # not as an empty root the builder writes into -- into the container
        # layer, gone with the next `up -d`, while the rollout reports ok
        # (review A4, 2026-09-03).
        p = Path(env)
        return p if p.is_dir() else None
    for cand in (Path("/data/agents-local"), _REPO / "data" / "agents"):
        if cand.is_dir():
            return cand
    return None


@dataclass(frozen=True)
class Roots:
    """``platform`` always; ``local`` when configured (it holds the agents)."""
    platform: Path
    local: Path | None = None

    def skill_roots(self) -> list[tuple[str, Path]]:
        out = [("platform", self.platform)]
        if self.local is not None:
            out.append(("local", self.local))
        return out


def roots(platform: Path | str | None = None, local: Path | str | None = None) -> Roots:
    """The roots to use: what was passed, else what the environment says."""
    return Roots(
        Path(platform) if platform else _default_platform(),
        Path(local) if local else (None if platform else _default_local()),
    )


# An id is a folder name, a config key, half a session key and part of a URL.
# The same alphabet the flow names use, for the same reasons.
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")

# Fields the manifest may carry. Anything else is refused on write rather than
# stored: a typo'd key ("skils") would otherwise be saved, ignored by the
# rollout, and look in the file exactly like a setting that works.
# Keys starting with "_" are comments and always allowed.
MANIFEST_KEYS = {
    "label", "icon", "colour", "description", "opening", "active", "sort_order",
    "model", "timeout", "limits", "skills", "tools", "workspace",
    "manage_workspace", "name", "soul_shared_with", "sensitive",
}

# Where the gateway keeps every agent's workspace. The manifest may name the
# workspace, but only THIS one: the value reaches a shell inside the gateway
# container, and a path that is not the agent's own is either a typo or an
# attempt -- both are refused, at save time and on every read of the roster.
WORKSPACE_ROOT = "/data/openclaw/agents"


def default_workspace(agent_id: str) -> str:
    return f"{WORKSPACE_ROOT}/{agent_id}/workspace"


def workspace_problem(manifest: dict, agent_id: str) -> str | None:
    """Why the manifest's path fields are not acceptable, or None.

    Two fields of a manifest become paths in the gateway: ``workspace``, and
    ``agentDir``, which the rollout copies into the config entry and uses to
    write the model catalogue. Both are bound to the id. ``agentDir`` is not
    in MANIFEST_KEYS, so the form refuses it already -- this is the other
    door, for a manifest written by hand, which load_roster does not validate.
    """
    ws = manifest.get("workspace")
    want = default_workspace(agent_id)
    if ws is not None and ws != want:
        return f"workspace must be {want!r} or left out (got {str(ws)[:80]!r})"
    ad = manifest.get("agentDir")
    if ad is not None and ad != f"{WORKSPACE_ROOT}/{agent_id}/agent":
        return (f"agentDir is the gateway's to set, not the manifest's — "
                f"leave it out (got {str(ad)[:80]!r})")
    return None


# The model policy of ADR-029 (point 6), as a check rather than a sentence:
# an agent that STEERS the house or handles SENSITIVE data runs on a local
# model. Steering is read off the tool list -- any tool whose risk is "act"
# reaches beyond the workspace, and an unrestricted list reaches everywhere.
# Sensitivity cannot be read off anything; it is declared in the manifest
# (`"sensitive": true`) by whoever knows what the agent will be handed.
# Locality is decided by the model id's prefix: the gateway's own `local`
# flag is false for llama-local (measured 2026-09-02), the prefix is not.
LOCAL_PREFIX = "llama-local/"

# The house's MCP tools that only read, search or take notes. Everything
# else the MCP server offers -- and everything it will offer that nobody has
# classified yet -- counts as acting: an unknown tool is the widest one, not
# the narrowest (ADR-029). The set used to be the other way round (the acting
# tools, listed), and a tool added to mcp_tools.py without a second edit was a
# reading tool by default. agents.py paints the builder from this same rule,
# so the form and the check cannot disagree.
MCP_READ_TOOLS = {"flows_list", "web_search", "web_read", "note", "notes_review", "verify", "run_status"}


def mcp_tool_risk(name: str) -> str:
    """read / act for one of the house's MCP tools, by its bare name."""
    return "read" if name in MCP_READ_TOOLS else "act"


def is_local_model(model: str | None) -> bool:
    return str(model or "").startswith(LOCAL_PREFIX)


def tool_risk(tool_id: str, rt: Roots | None = None, builtin: list[dict] | None = None) -> str:
    """read / write / act for one allow-list entry. An MCP tool is judged by
    its name behind the server prefix; a gateway tool by tools.json; an id
    nobody knows is `act` -- the same reading the builder gives it, because an
    unknown tool is the widest one, not the narrowest.

    ``builtin`` is tools.json already read; a caller judging a whole list
    passes it once rather than having the file read per entry.
    """
    if "__" in tool_id:
        return mcp_tool_risk(tool_id.split("__", 1)[1])
    for t in builtin if builtin is not None else builtin_tools(rt):
        if t.get("id") == tool_id:
            return str(t.get("risk") or "act")
    return "act"


def local_reasons(manifest: dict, rt: Roots | None = None) -> list[str]:
    """Why this agent must run on a local model. Empty means it need not."""
    reasons: list[str] = []
    if manifest.get("sensitive") is True:
        reasons.append("it is marked sensitive (handles data that must not leave the house)")
    tools = manifest.get("tools")
    if tools == "unrestricted":
        reasons.append("its tools are unrestricted")
    elif isinstance(tools, dict) and isinstance(tools.get("allow"), list):
        builtin = builtin_tools(rt)
        acting = [t for t in tools["allow"] if isinstance(t, str) and tool_risk(t, rt, builtin) == "act"]
        if acting:
            reasons.append(f"it holds acting tool(s): {', '.join(acting)}")
    return reasons

LIMIT_KEYS = {
    "page_chars", "max_urls", "max_queries", "snippet_chars",
    "results_per_query", "max_pages_total", "max_searches_total",
}

# Per-agent workspace files besides SOUL.md. The rollout renders exactly these
# (deploy.desired_workspace_files); the builder edits exactly these. One list, two
# readers -- a fifth file added here alone would be edited and never rendered.
WORKSPACE_EXTRA = ["TOOLS.md", "USER.md", "IDENTITY.md"]

# Skill files the browser may preview. Text only: a skill may carry a template
# image one day, and a binary shown as text is noise, not information.
_TEXT_SUFFIXES = {".md", ".txt", ".json", ".yaml", ".yml", ".csv"}
_PREVIEW_MAX = 200_000


class StoreError(RuntimeError):
    """Something the store refuses. The three kinds below say what to do about
    it, so a caller does not have to read the message to find out.

    The HTTP layer used to decide by sniffing the text
    (``startswith("no agent")``) in one place and by hard-coding a status in
    two others -- three rules for one question, and rewording a message
    silently changed a status code (review 2, section D).
    """


class NotFound(StoreError):
    """The agent, skill or file asked for is not there."""


class Invalid(StoreError):
    """What was asked for cannot be stored, or what is stored cannot be read."""


class NoRoot(StoreError):
    """There is nowhere to keep agents: no installation root is configured."""


def _r(rt: Roots | None) -> Roots:
    return rt if rt is not None else roots()


# ---------------------------------------------------------------------------
# finding things
# ---------------------------------------------------------------------------

def instances_dir(rt: Roots | None = None) -> Path | None:
    """Where the agents live, or None when no installation root is configured."""
    rt = _r(rt)
    return None if rt.local is None else rt.local / "instances"


def _instance_folders(rt: Roots | None = None) -> tuple[list[Path], list[str]]:
    """(folders whose name is an id, names that are not). Dot folders skipped."""
    inst = instances_dir(rt)
    if inst is None or not inst.is_dir():
        return [], []
    good: list[Path] = []
    bad: list[str] = []
    for f in sorted(inst.iterdir()):
        if not f.is_dir() or f.name.startswith("."):
            continue
        if ID_RE.match(f.name):
            good.append(f)
        else:
            bad.append(f.name)
    return good, bad


def iter_instances(rt: Roots | None = None) -> list[Path]:
    """Every instance folder that can be looked up by name.

    A folder whose name is not an id is SKIPPED here and refused by
    load_roster: ``instances/Recherche_DE/`` used to be rolled out while the
    detail view said "no agent" (review B10). Raising here instead was worse
    than the bug -- this function also carries the chat's agent list, the
    delete path and the skill pages, and one stray folder took all three down
    with it. The rollout is the door where the refusal belongs, because being
    rolled out was the harm.
    """
    return _instance_folders(rt)[0]


def stray_instance_names(rt: Roots | None = None) -> list[str]:
    """Folder names under instances/ that cannot be an agent id."""
    return _instance_folders(rt)[1]


def find_instance(agent_id: str, rt: Roots | None = None) -> Path | None:
    inst = instances_dir(rt)
    if inst is None or not ID_RE.match(agent_id):
        return None
    folder = inst / agent_id
    return folder if folder.is_dir() else None


def find_skill(name: str, rt: Roots | None = None) -> tuple[str, Path] | None:
    """(root name, folder) of a skill, or None. Raises when it is in both."""
    if not ID_RE.match(name):
        return None
    hits = [(n, root / "skills" / name) for n, root in _r(rt).skill_roots()
            if (root / "skills" / name / "SKILL.md").is_file()]
    if len(hits) > 1:
        raise Invalid(f"skill {name!r} exists in both agents/skills and data/agents/skills — rename or remove one")
    return hits[0] if hits else None


# ---------------------------------------------------------------------------
# reading
# ---------------------------------------------------------------------------

def load_manifest(agent_id: str, rt: Roots | None = None) -> dict:
    """One agent's manifest, or {} when there is none. Never raises: a broken
    manifest must hide itself and not the others."""
    folder = find_instance(agent_id, rt)
    if folder is None:
        return {}
    try:
        return json.loads((folder / "agent.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def effective_limits(manifest: dict, rt: Roots | None = None, _depth: int = 0) -> dict | None:
    """The payload limits an agent runs with, following ``same_as``.

    Returns the dict of limits, or None when the manifest has none. A reference
    to an agent that does not exist or has no limits resolves to None as well --
    and the roster's validation reports it, so the silence here is not the
    last word.
    """
    limits = manifest.get("limits")
    if not isinstance(limits, dict):
        return None
    ref = limits.get("same_as")
    if not ref:
        return limits
    if _depth > 3:  # a cycle, or someone being clever
        return None
    return effective_limits(load_manifest(str(ref), rt), rt, _depth + 1)


def soul_source(agent_id: str, rt: Roots | None = None) -> tuple[str | None, Path | None]:
    """(id whose SOUL this agent uses, path of that SOUL file).

    Own file -> (None, path). Borrowed by manifest -> (other, other's path).
    Borrowed by the one legacy symlink -> (other, path through the link).
    Nothing -> (None, None).
    """
    folder = find_instance(agent_id, rt)
    if folder is None:
        return None, None
    ref = load_manifest(agent_id, rt).get("soul_shared_with")
    if ref:
        other = find_instance(str(ref), rt)
        if other is None or not (other / "SOUL.md").is_file():
            return str(ref), None
        return str(ref), other / "SOUL.md"
    sp = folder / "SOUL.md"
    if sp.is_symlink():
        target = Path(os.readlink(sp))
        other = target.parent.name if target.name == "SOUL.md" else str(target)
        return other, (sp if sp.exists() else None)
    return None, (sp if sp.is_file() else None)


def load_letterbox(rt: Roots | None = None) -> dict | None:
    """The reception desk's entry from <platform>/gateway.json, or None."""
    path = _r(rt).platform / "gateway.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise Invalid(f"cannot read gateway.json: {e}") from e
    entry = data.get("letterbox")
    if not isinstance(entry, dict):
        raise Invalid("gateway.json has no 'letterbox' object")
    entry = dict(entry)
    entry.setdefault("id", LETTERBOX_ID)
    entry["manage_workspace"] = False
    entry["active"] = False
    entry["_platform"] = True
    return entry


def load_roster(rt: Roots | None = None) -> dict:
    """Read the roster by LOOKING, not by consulting a list of names.

    One folder under data/agents/instances/ is one agent, and its folder name
    is its id. That is the whole point of increment 3: a new agent comes into
    being by being written down somewhere, and nothing else has to be edited to
    admit it -- no list, no registry, no line of code.

    Returns {"agents": [...], "letterbox": {...}|None, "mcp": {...}}. An empty
    agents list is a legitimate state -- a fresh clone has none.
    """
    rt = _r(rt)
    if not rt.platform.is_dir():
        raise NotFound(f"no platform root at {rt.platform}")

    agents: list[dict] = []
    for name in stray_instance_names(rt):
        raise Invalid(
            f"instances/{name}: not a valid agent id (lowercase letters, digits "
            f"and dashes, 2-64 characters) -- rename the folder. It cannot be "
            f"deployed: nothing could look it up again afterwards."
        )
    for folder in iter_instances(rt):
        if folder.name == LETTERBOX_ID:
            raise Invalid(
                f"instances/{LETTERBOX_ID} is not an agent — the reception desk is "
                f"configured in agents/gateway.json. Remove the folder."
            )
        manifest = folder / "agent.json"
        if not manifest.is_file():
            # Named rather than skipped: a folder without a manifest is far more
            # likely a half-finished agent than a deliberate placeholder, and a
            # silently ignored agent is the failure this layer keeps guarding
            # against.
            raise Invalid(
                f"instances/{folder.name} has no agent.json — an instance folder "
                f"without one cannot be deployed. Remove the folder or give it a manifest."
            )
        try:
            agent = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise Invalid(f"cannot read instances/{folder.name}/agent.json: {e}") from e

        # The id is the folder name, never a field. Two sources for one identity
        # is one source too many, and a manifest whose id disagrees with its
        # folder is a bug waiting for someone to rename one of them.
        agent["id"] = folder.name
        bad_ws = workspace_problem(agent, folder.name)
        if bad_ws:
            raise Invalid(f"instances/{folder.name}: {bad_ws}")
        agent.setdefault("workspace", default_workspace(folder.name))
        agent.setdefault("manage_workspace", True)
        agent["_dir"] = str(folder)
        agents.append(agent)

    # References must point somewhere. Checked on every read of the roster, so
    # a rollout refuses a dangling borrow instead of quietly running the agent
    # on defaults sized for a different model, or without a personality. The
    # rule is the form's rule (reference_problems): one wording at both doors.
    for agent in agents:
        for why in reference_problems(agent, agent["id"], rt):
            raise Invalid(f"instances/{agent['id']}: {why}")

    mcp: dict = {}
    mcp_file = rt.platform / "mcp.json"
    if mcp_file.is_file():
        try:
            mcp = json.loads(mcp_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise Invalid(f"cannot read mcp.json: {e}") from e

    return {"agents": agents, "letterbox": load_letterbox(rt), "mcp": mcp}


def skills_catalog(rt: Roots | None = None) -> list[dict]:
    """The skills both roots offer, read from each SKILL.md's front matter.

    Only ``name`` and ``description`` are read -- the description is the part
    that reaches a prompt, so it is the part a person choosing a skill needs
    to see. A skill present in both roots is an error.
    """
    out: list[dict] = []
    seen: dict[str, str] = {}
    for root_name, root in _r(rt).skill_roots():
        skills_root = root / "skills"
        if not skills_root.is_dir():
            continue
        for folder in sorted(skills_root.iterdir()):
            sk = folder / "SKILL.md"
            if not folder.is_dir() or folder.name.startswith(".") or not sk.is_file():
                continue
            if folder.name in seen:
                raise Invalid(f"skill {folder.name!r} exists in both agents/skills and data/agents/skills — rename or remove one")
            seen[folder.name] = root_name
            meta = _front_matter(sk.read_text(encoding="utf-8", errors="replace"))
            out.append({
                "name": folder.name,
                "root": root_name,
                "description": meta.get("description", ""),
                "files": sum(1 for f in folder.rglob("*") if f.is_file()),
            })
    return out


def _front_matter(text: str) -> dict:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    meta: dict = {}
    for line in text[3:end].splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
    return meta


def builtin_tools(rt: Roots | None = None) -> list[dict]:
    """The gateway's own tools, as curated in <platform>/tools.json.

    A list in the repo, and knowingly so -- the plan preferred asking the
    gateway, but the gateway has no command that lists its tool ids with what
    each one can do, and the builder needs the second half more than the first:
    a checkbox labelled ``exec`` says nothing, one labelled "runs shell
    commands" is a decision. Drift against the gateway is possible and is
    caught where it would matter: an id the gateway does not know is refused
    by ``config patch`` at rollout.
    """
    path = _r(rt).platform / "tools.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [t for t in data.get("tools", []) if isinstance(t, dict) and t.get("id")]


def instance_detail(agent_id: str, rt: Roots | None = None) -> dict:
    """Everything the builder shows for one agent: manifest, SOUL text, whose
    SOUL it is, the other workspace files."""
    folder = find_instance(agent_id, rt)
    if folder is None or not (folder / "agent.json").is_file():
        raise NotFound(f"no agent {agent_id!r}")
    manifest = load_manifest(agent_id, rt)
    shared, soul_path = soul_source(agent_id, rt)
    soul = soul_path.read_text(encoding="utf-8", errors="replace") if soul_path else ""
    files: dict[str, str] = {}
    for name in WORKSPACE_EXTRA:
        fp = folder / name
        if fp.is_file():
            files[name] = fp.read_text(encoding="utf-8", errors="replace")
    return {
        "id": agent_id,
        "manifest": manifest,
        "soul": soul,
        "soul_shared_with": shared,
        "files": files,
        "limits_effective": effective_limits(manifest, rt),
    }


def skill_detail(name: str, rt: Roots | None = None) -> dict:
    """One skill with every file it carries, for reading in the browser.

    Why this exists: the builder showed a skill as a name, a description and
    "5 Datei(en)", and the first person to use it asked where the eight
    questions were. They were in FRAGEN.md, two folders down, visible to the
    agent and to nobody else. A skill's files are the part of an agent that is
    most worth reading and were the only part that could not be.

    Read-only on purpose. Writing skill files is a different decision: skills
    are shared between agents and come in three tiers with three homes
    (ADR-029).
    """
    hit = find_skill(name, rt)
    if hit is None:
        raise NotFound(f"no skill {name!r}")
    root_name, folder = hit
    meta = _front_matter((folder / "SKILL.md").read_text(encoding="utf-8", errors="replace"))
    files = []
    for f in sorted(folder.rglob("*")):
        if not f.is_file() or f.name.startswith("."):
            continue
        entry: dict = {"path": str(f.relative_to(folder)), "size": f.stat().st_size}
        if f.suffix.lower() in _TEXT_SUFFIXES and entry["size"] <= _PREVIEW_MAX:
            entry["content"] = f.read_text(encoding="utf-8", errors="replace")
        files.append(entry)
    used_by = sorted(f.name for f in iter_instances(rt)
                     if name in (load_manifest(f.name, rt).get("skills") or []))
    return {"name": name, "root": root_name, "description": meta.get("description", ""),
            "files": files, "used_by": used_by}


# ---------------------------------------------------------------------------
# writing
# ---------------------------------------------------------------------------

def _inherit_owner(path: Path) -> None:
    """Give ``path`` the uid/gid AND the mode of its parent directory.

    Best effort and root-only in effect: as a normal user chown to someone
    else fails, and as a normal user the file already belongs to the right
    person. Inside the container, root writes into a bind mount, and this is
    what keeps the checkout writable by the person who owns it.

    The mode matters as much as the owner. Measured on the first live run: the
    container's umask made 644 files in a tree that is 664 throughout, so the
    owner's group -- the person at the keyboard -- could read them and not edit
    them. A folder gets its parent's mode; a file gets it minus the execute
    bits. Symlinks are left alone: their mode is meaningless.
    """
    try:
        st = path.parent.stat()
        os.chown(path, st.st_uid, st.st_gid, follow_symlinks=False)
        if not path.is_symlink():
            mode = st.st_mode & 0o777
            os.chmod(path, mode if path.is_dir() else mode & ~0o111)
    except (OSError, PermissionError):
        pass


def reference_problems(manifest: dict, agent_id: str, rt: Roots | None = None) -> list[str]:
    """Why the manifest's borrows do not resolve. Empty means they do.

    ``limits.same_as`` and ``soul_shared_with`` name another agent; a borrow
    that points nowhere, at itself, or at another borrower is refused. One
    function for both doors -- the form (validate_manifest) and the roster
    (load_roster) -- because two wordings of one rule drift apart.
    """
    problems: list[str] = []
    lim = manifest.get("limits")
    if isinstance(lim, dict) and lim.get("same_as"):
        ref = str(lim["same_as"])
        if ref == agent_id:
            problems.append("limits.same_as cannot point at the agent itself")
        elif effective_limits({"limits": {"same_as": ref}}, rt) is None:
            problems.append(f"limits.same_as = {ref!r}: that agent does not exist or has no limits of its own")
    ref = manifest.get("soul_shared_with")
    if ref:
        ref = str(ref)
        if ref == agent_id:
            problems.append("soul_shared_with cannot point at the agent itself")
        else:
            other_shared, path = soul_source(ref, rt)
            if find_instance(ref, rt) is None or path is None:
                problems.append(f"soul_shared_with = {ref!r}: that agent does not exist or has no SOUL.md")
            elif other_shared:
                problems.append(f"soul_shared_with = {ref!r}: that agent borrows its SOUL itself — point at the original ({other_shared})")
    return problems


def validate_manifest(manifest: dict, agent_id: str, rt: Roots | None = None) -> list[str]:
    """Reasons a manifest cannot be saved. Empty means it can.

    Refuses the same things the rollout would refuse, so the builder fails at
    the form and not at "Save → Deploy → Error". The messages are for
    people, not logs: they name the field and say what is wrong with it.
    """
    problems: list[str] = []
    unknown = [k for k in manifest if not k.startswith("_") and k not in MANIFEST_KEYS]
    if unknown:
        problems.append(f"unknown field(s): {', '.join(sorted(unknown))}")
    if not str(manifest.get("label") or "").strip():
        problems.append("label is required")
    if not str(manifest.get("model") or "").strip():
        problems.append("model is required")
    bad_ws = workspace_problem(manifest, agent_id)
    if bad_ws:
        problems.append(bad_ws)
    tools = manifest.get("tools")
    if tools != "unrestricted":
        if not isinstance(tools, dict) or not isinstance(tools.get("allow"), list):
            problems.append("tools.allow must be a list (or tools = \"unrestricted\", written out)")
        elif not tools["allow"]:
            problems.append("tools.allow is empty — the gateway refuses a run with no callable tool; name at least one")
    skills = manifest.get("skills", [])
    if not isinstance(skills, list):
        problems.append("skills must be a list")
    else:
        try:
            known = {s["name"] for s in skills_catalog(rt)}
        except StoreError as e:
            known, problems = set(), problems + [str(e)]
        for s in skills:
            if s not in known:
                problems.append(f"skill {s!r} does not exist under agents/skills or data/agents/skills")
    lim = manifest.get("limits")
    if lim is not None:
        if not isinstance(lim, dict):
            problems.append("limits must be an object")
        elif lim.get("same_as"):
            extra = [k for k in lim if k != "same_as"]
            if extra:
                problems.append("limits.same_as cannot be combined with own values — that is the drift it exists to prevent")
        else:
            for k, v in lim.items():
                if k not in LIMIT_KEYS:
                    problems.append(f"unknown limit {k!r}")
                elif not isinstance(v, int) or v <= 0:
                    problems.append(f"limit {k} must be a positive integer")
    problems += reference_problems(manifest, agent_id, rt)
    t = manifest.get("timeout")
    if t is not None and (not isinstance(t, int) or t <= 0):
        problems.append("timeout must be a positive integer (seconds)")
    if "sensitive" in manifest and not isinstance(manifest["sensitive"], bool):
        problems.append("sensitive must be true or false")
    # ADR-029 point 6, enforced: steering or sensitive means local, and a cloud
    # model is refused here at the form, not later at the rollout.
    why = local_reasons(manifest, rt)
    if why and not is_local_model(manifest.get("model")):
        problems.append(
            f"model {manifest.get('model')!r} is not local, but this agent must run locally: "
            + "; ".join(why) + f". Choose a {LOCAL_PREFIX}* model, or drop the acting tools / the sensitive mark."
        )
    return problems


def save_instance(agent_id: str, manifest: dict, *, soul: str | None = None,
                  soul_shared_with: str | None = None,
                  files: dict[str, str] | None = None,
                  rt: Roots | None = None) -> dict:
    """Write one agent's folder. Creates it if new, replaces manifest and SOUL
    if not. Returns {"created": bool, "path": str}.

    ``soul_shared_with`` writes the reference into the manifest and removes any
    SOUL.md of the agent's own -- identity by construction. ``soul`` writes an
    own SOUL.md and drops the reference. Passing both is a caller's confusion
    and is refused rather than guessed at.

    ``files`` names workspace files from WORKSPACE_EXTRA: a name that is absent
    is left alone, a string is written, an empty string removes the file. Said
    this plainly because "empty textarea" is ambiguous in a form and must not
    be ambiguous in a folder.
    """
    rt = _r(rt)
    if not ID_RE.match(agent_id):
        raise Invalid("id: 2–64 characters, lowercase letters, digits and hyphens, starting with a letter or digit")
    if agent_id == LETTERBOX_ID:
        raise Invalid(f"{LETTERBOX_ID!r} is the gateway's reception desk, not an agent — "
                         f"its tool list lives in agents/gateway.json")
    if soul is not None and soul_shared_with:
        raise Invalid("either a SOUL text or a SOUL to share, not both")
    for name, body in (files or {}).items():
        if name not in WORKSPACE_EXTRA:
            raise Invalid(f"{name!r} is not a workspace file an agent may carry "
                             f"(one of {', '.join(WORKSPACE_EXTRA)})")
        # Checked HERE, with the names, and not where the file is written: the
        # manifest and SOUL.md are replaced first, so a value that only fails
        # at the writing step left the agent changed behind a 500 the caller
        # read as "rejected" (review 2, finding 8). Everything this function
        # can refuse, it refuses before it writes anything.
        if not isinstance(body, str):
            raise Invalid(
                f"{name}: a workspace file is text — leave the key out to keep "
                f"the file as it is, or pass \"\" to remove it "
                f"(got {type(body).__name__})"
            )
    inst = instances_dir(rt)
    if inst is None:
        raise NoRoot("no installation root configured (MORA02_AGENTS_LOCAL_DIR) — "
                         "nowhere to put an agent")

    # The reference lives in the manifest so the rollout sees it too.
    clean = {k: v for k, v in manifest.items() if k not in ("id", "_dir")}
    if soul_shared_with:
        clean["soul_shared_with"] = soul_shared_with
    elif soul is not None:
        clean.pop("soul_shared_with", None)
    problems = validate_manifest(clean, agent_id, rt)
    if problems:
        raise Invalid("; ".join(problems))

    folder = inst / agent_id
    created = not folder.exists()
    if created:
        inst.mkdir(parents=True, exist_ok=True)
        folder.mkdir()
        _inherit_owner(folder)

    mpath = folder / "agent.json"
    tmp = mpath.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(clean, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _inherit_owner(tmp)
    os.replace(tmp, mpath)

    soul_path = folder / "SOUL.md"
    if soul_shared_with:
        # Borrowed: no file of its own, or a stale one would shadow the borrow
        # in anyone's eyes but the rollout's.
        if soul_path.is_symlink() or soul_path.exists():
            soul_path.unlink()
    elif soul is not None:
        if soul_path.is_symlink():
            # Was a legacy link: break it, do not write through it into the
            # other agent's file.
            soul_path.unlink()
        soul_path.write_text(soul if soul.endswith("\n") else soul + "\n", encoding="utf-8")
        _inherit_owner(soul_path)

    for name, body in (files or {}).items():
        fp = folder / name
        if body == "":
            if fp.exists() or fp.is_symlink():
                fp.unlink()
            continue
        fp.write_text(body if body.endswith("\n") else body + "\n", encoding="utf-8")
        _inherit_owner(fp)

    return {"created": created, "path": str(folder)}


def trash_instance(agent_id: str, rt: Roots | None = None) -> dict:
    """Move an instance folder to instances/.trash/<id>-<stamp>.

    Refuses an agent whose SOUL other agents borrow: those would render without
    a personality, silently.
    """
    rt = _r(rt)
    folder = find_instance(agent_id, rt)
    if folder is None:
        raise NotFound(f"no agent {agent_id!r}")
    dependants = sorted(f.name for f in iter_instances(rt)
                        if f.name != agent_id and soul_source(f.name, rt)[0] == agent_id)
    if dependants:
        raise Invalid(
            f"{agent_id!r} lends its SOUL to {', '.join(dependants)} — give them "
            f"their own first, or delete them first"
        )
    trash = folder.parent / ".trash"
    if not trash.exists():
        trash.mkdir()
        _inherit_owner(trash)
    dest = trash / f"{agent_id}-{time.strftime('%Y%m%d%H%M%S')}"
    shutil.move(str(folder), str(dest))
    return {"moved_to": str(dest)}
