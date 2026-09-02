"""The agent roster as files: reading it by looking, and writing it back.

One folder under ``agents/instances/`` is one agent; its folder name is its id.
This module is the only place that knows the folder layout, so the rollout
(:mod:`mora02_core.agents.deploy`), the HTTP layer in script-runner and the
tests all read and write the same shape without each carrying a copy of it.

What an instance folder holds::

    instances/<id>/agent.json   the manifest: label, model, tools, skills, limits
    instances/<id>/SOUL.md      its personality -- a file, or a symlink to
                                another instance's, which is how two agents
                                share one identity by construction

Two rules enforced here rather than in a UI, because a UI is one door of two:

* **Limits may be borrowed.** ``"limits": {"same_as": "<id>"}`` resolves to the
  other agent's limits at read time. Measured 2026-09-02: six payload values
  that differed between two instances invalidated a whole day's comparison of
  the models behind them. A reference cannot drift; a copy does within a week.
* **Deletion moves, it does not remove.** A deleted instance goes to
  ``instances/.trash/<id>-<stamp>`` -- invisible to roster and rollout (dot
  folder), recoverable by moving it back, and the record the rollout reads to
  know the gateway's copy should go too.

Ownership: script-runner runs as root inside its container, and the folder is a
bind mount of a git checkout. A file written here would otherwise belong to
root on the host, and the next ``git add`` by the person would fail. So every
file and folder this module creates inherits uid/gid from the directory above
it -- the folder decides who owns what is in it.

Environment:
  MORA02_AGENTS_DIR  the ``agents/`` folder; default ``/data/agents`` when that
                     exists (the container mount), else the repo's own
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path


def _default_agents_dir() -> Path:
    env = os.environ.get("MORA02_AGENTS_DIR")
    if env:
        return Path(env)
    mount = Path("/data/agents")
    if mount.is_dir():
        return mount
    return Path(__file__).resolve().parents[5] / "agents"


AGENTS_DIR = _default_agents_dir()

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
    "manage_workspace", "name",
}

LIMIT_KEYS = {
    "page_chars", "max_urls", "max_queries", "snippet_chars",
    "results_per_query", "max_pages_total", "max_searches_total",
}


class StoreError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# reading
# ---------------------------------------------------------------------------

def instances_dir(agents_dir: Path | None = None) -> Path:
    return Path(agents_dir or AGENTS_DIR) / "instances"


def load_manifest(agent_id: str, agents_dir: Path | None = None) -> dict:
    """One agent's manifest, or {} when there is none. Never raises: a broken
    manifest must hide itself and not the others."""
    path = instances_dir(agents_dir) / agent_id / "agent.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def effective_limits(manifest: dict, agents_dir: Path | None = None,
                     _depth: int = 0) -> dict | None:
    """The payload limits an agent runs with, following ``same_as``.

    Returns the dict of limits, or None when the manifest has none. A reference
    to an agent that does not exist or has no limits resolves to None as well --
    and the rollout's validation reports it, so the silence here is not the
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
    return effective_limits(load_manifest(str(ref), agents_dir), agents_dir, _depth + 1)


def load_roster(agents_dir: Path | None = None) -> dict:
    """Read the roster by LOOKING, not by consulting a list of names.

    One folder under agents/instances/ is one agent, and its folder name is its
    id. That is the whole point of increment 3: a new agent comes into being by
    being written down somewhere, and nothing else has to be edited to admit it
    -- no list, no registry, no line of code. The builder therefore only ever
    has to create a directory.
    """
    base = Path(agents_dir or AGENTS_DIR)
    inst = base / "instances"
    if not inst.is_dir():
        raise StoreError(f"no instance directory at {inst}")

    agents: list[dict] = []
    for folder in sorted(inst.iterdir()):
        if not folder.is_dir() or folder.name.startswith("."):
            continue
        manifest = folder / "agent.json"
        if not manifest.is_file():
            # Named rather than skipped: a folder without a manifest is far more
            # likely a half-finished agent than a deliberate placeholder, and a
            # silently ignored agent is the failure this layer keeps guarding
            # against.
            raise StoreError(
                f"instances/{folder.name} has no agent.json — an instance "
                f"folder without one cannot be deployed. Remove the folder or "
                f"give it a manifest."
            )
        try:
            agent = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise StoreError(f"cannot read instances/{folder.name}/agent.json: {e}") from e

        # The id is the folder name, never a field. Two sources for one identity
        # is one source too many, and a manifest whose id disagrees with its
        # folder is a bug waiting for someone to rename one of them.
        agent["id"] = folder.name
        agent.setdefault("workspace", f"/data/openclaw/agents/{folder.name}/workspace")
        agent.setdefault("manage_workspace", True)
        agent["_dir"] = str(folder)

        # A borrowed limits block must point somewhere. Checked here, on every
        # read of the roster, so a rollout refuses a dangling reference instead
        # of quietly running the agent on defaults sized for a different model.
        lim = agent.get("limits")
        if isinstance(lim, dict) and lim.get("same_as"):
            ref = str(lim["same_as"])
            if ref == folder.name:
                raise StoreError(f"instances/{folder.name}: limits.same_as points at itself")
            if effective_limits(agent, base) is None:
                raise StoreError(
                    f"instances/{folder.name}: limits.same_as = {ref!r}, but that "
                    f"agent does not exist or has no limits of its own"
                )
        agents.append(agent)

    if not agents:
        raise StoreError(f"no agents found under {inst}")

    mcp: dict = {}
    mcp_file = base / "mcp.json"
    if mcp_file.is_file():
        try:
            mcp = json.loads(mcp_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise StoreError(f"cannot read mcp.json: {e}") from e

    return {"agents": agents, "mcp": mcp}


def skills_catalog(agents_dir: Path | None = None) -> list[dict]:
    """The skills the repo offers, read from each SKILL.md's front matter.

    Only ``name`` and ``description`` are read -- the description is the part
    that reaches a prompt, so it is the part a person choosing a skill needs
    to see. Files that carry no front matter are listed by folder name with an
    empty description, which the builder shows as the warning it is.
    """
    skills_root = Path(agents_dir or AGENTS_DIR) / "skills"
    out: list[dict] = []
    if not skills_root.is_dir():
        return out
    for folder in sorted(skills_root.iterdir()):
        sk = folder / "SKILL.md"
        if not folder.is_dir() or folder.name.startswith(".") or not sk.is_file():
            continue
        meta = _front_matter(sk.read_text(encoding="utf-8", errors="replace"))
        out.append({
            "name": folder.name,
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


def builtin_tools(agents_dir: Path | None = None) -> list[dict]:
    """The gateway's own tools, as curated in agents/tools.json.

    A list in the repo, and knowingly so -- the plan preferred asking the
    gateway, but the gateway has no command that lists its tool ids with what
    each one can do, and the builder needs the second half more than the first:
    a checkbox labelled ``exec`` says nothing, one labelled "runs shell
    commands" is a decision. Drift against the gateway is possible and is
    caught where it would matter: an id the gateway does not know is refused
    by ``config patch`` at rollout.
    """
    path = Path(agents_dir or AGENTS_DIR) / "tools.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [t for t in data.get("tools", []) if isinstance(t, dict) and t.get("id")]


def instance_detail(agent_id: str, agents_dir: Path | None = None) -> dict:
    """Everything the builder shows for one agent: manifest, SOUL text, and
    whether the SOUL is its own or shared."""
    folder = instances_dir(agents_dir) / agent_id
    if not (folder / "agent.json").is_file():
        raise StoreError(f"no agent {agent_id!r}")
    manifest = load_manifest(agent_id, agents_dir)
    soul_path = folder / "SOUL.md"
    soul, shared = "", None
    if soul_path.is_symlink():
        # "../recherche/SOUL.md" -> "recherche"
        target = Path(os.readlink(soul_path))
        shared = target.parent.name if target.name == "SOUL.md" else str(target)
    if soul_path.exists():
        soul = soul_path.read_text(encoding="utf-8", errors="replace")
    return {
        "id": agent_id,
        "manifest": manifest,
        "soul": soul,
        "soul_shared_with": shared,
        "limits_effective": effective_limits(manifest, agents_dir),
    }


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


def validate_manifest(manifest: dict, agent_id: str, agents_dir: Path | None = None) -> list[str]:
    """Reasons a manifest cannot be saved. Empty means it can.

    Refuses the same things the rollout would refuse, so the builder fails at
    the form and not at "Speichern → Rollout → Fehler". The messages are for
    people, not logs: they name the field and say what is wrong with it.
    """
    problems: list[str] = []
    unknown = [k for k in manifest if not k.startswith("_") and k not in MANIFEST_KEYS]
    if unknown:
        problems.append(f"unknown field(s): {', '.join(sorted(unknown))}")
    if not str(manifest.get("label") or "").strip():
        problems.append("label is required")
    if not str(manifest.get("model") or "").strip() and agent_id != "main":
        problems.append("model is required")
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
        known = {s["name"] for s in skills_catalog(agents_dir)}
        for s in skills:
            if s not in known:
                problems.append(f"skill {s!r} does not exist under agents/skills/")
    lim = manifest.get("limits")
    if lim is not None:
        if not isinstance(lim, dict):
            problems.append("limits must be an object")
        elif lim.get("same_as"):
            ref = str(lim["same_as"])
            if ref == agent_id:
                problems.append("limits.same_as cannot point at the agent itself")
            elif effective_limits({"limits": {"same_as": ref}}, agents_dir) is None:
                problems.append(f"limits.same_as = {ref!r}: that agent does not exist or has no limits of its own")
            extra = [k for k in lim if k != "same_as"]
            if extra:
                problems.append("limits.same_as cannot be combined with own values — that is the drift it exists to prevent")
        else:
            for k, v in lim.items():
                if k not in LIMIT_KEYS:
                    problems.append(f"unknown limit {k!r}")
                elif not isinstance(v, int) or v <= 0:
                    problems.append(f"limit {k} must be a positive integer")
    t = manifest.get("timeout")
    if t is not None and (not isinstance(t, int) or t <= 0):
        problems.append("timeout must be a positive integer (seconds)")
    return problems


def save_instance(agent_id: str, manifest: dict, *, soul: str | None = None,
                  soul_shared_with: str | None = None,
                  agents_dir: Path | None = None) -> dict:
    """Write one agent's folder. Creates it if new, replaces the manifest and
    SOUL.md if not. Returns {"created": bool, "path": str}.

    ``soul_shared_with`` makes SOUL.md a symlink to that agent's -- identity by
    construction, the form the two research agents already use. ``soul`` and
    ``soul_shared_with`` are exclusive; passing both is a caller's confusion
    and is refused rather than guessed at.
    """
    if not ID_RE.match(agent_id):
        raise StoreError("id: 2–64 characters, lowercase letters, digits and hyphens, starting with a letter or digit")
    if agent_id in ("main",) and manifest.get("active"):
        raise StoreError("main cannot be made active: it is the letterbox on the message channel, not a persona")
    problems = validate_manifest(manifest, agent_id, agents_dir)
    if problems:
        raise StoreError("; ".join(problems))
    if soul is not None and soul_shared_with:
        raise StoreError("either a SOUL text or a SOUL to share, not both")
    if soul_shared_with:
        if soul_shared_with == agent_id:
            raise StoreError("an agent cannot share its SOUL with itself")
        src = instances_dir(agents_dir) / soul_shared_with / "SOUL.md"
        if not src.is_file():
            raise StoreError(f"cannot share SOUL with {soul_shared_with!r}: it has no SOUL.md")
        if src.is_symlink():
            raise StoreError(f"{soul_shared_with!r} shares its SOUL itself — point at the original")

    folder = instances_dir(agents_dir) / agent_id
    created = not folder.exists()
    if created:
        folder.mkdir(parents=False)
        _inherit_owner(folder)

    # Fields the rollout adds at read time never go back into the file. The
    # id is the folder; "_dir" is a runtime handle. Both in the manifest would
    # be two sources for one fact.
    clean = {k: v for k, v in manifest.items() if k not in ("id", "_dir")}
    mpath = folder / "agent.json"
    tmp = mpath.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(clean, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _inherit_owner(tmp)
    os.replace(tmp, mpath)

    soul_path = folder / "SOUL.md"
    if soul_shared_with:
        if soul_path.is_symlink() or soul_path.exists():
            soul_path.unlink()
        os.symlink(f"../{soul_shared_with}/SOUL.md", soul_path)
        _inherit_owner(soul_path)
    elif soul is not None:
        if soul_path.is_symlink():
            # Was shared, now its own: break the link, do not write through it
            # into the other agent's file.
            soul_path.unlink()
        soul_path.write_text(soul if soul.endswith("\n") else soul + "\n", encoding="utf-8")
        _inherit_owner(soul_path)

    return {"created": created, "path": str(folder)}


def trash_instance(agent_id: str, agents_dir: Path | None = None) -> dict:
    """Move an instance folder to instances/.trash/<id>-<stamp>.

    Refuses to trash an agent whose SOUL other agents link to: the links would
    dangle and those agents would render without a personality, silently.
    """
    inst = instances_dir(agents_dir)
    folder = inst / agent_id
    if not folder.is_dir():
        raise StoreError(f"no agent {agent_id!r}")
    if agent_id == "main":
        raise StoreError("main is the gateway's own agent and cannot be deleted")
    dependants = []
    for other in inst.iterdir():
        sp = other / "SOUL.md"
        if other.is_dir() and other.name != agent_id and sp.is_symlink():
            if Path(os.readlink(sp)).parent.name == agent_id:
                dependants.append(other.name)
    if dependants:
        raise StoreError(
            f"{agent_id!r} lends its SOUL to {', '.join(dependants)} — give them "
            f"their own first, or delete them first"
        )
    trash = inst / ".trash"
    if not trash.exists():
        trash.mkdir()
        _inherit_owner(trash)
    dest = trash / f"{agent_id}-{time.strftime('%Y%m%d%H%M%S')}"
    shutil.move(str(folder), str(dest))
    return {"moved_to": str(dest)}
