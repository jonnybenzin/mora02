#!/usr/bin/env python3
"""Does the builder's store keep the promises the rollout relies on?

Increment 4 lets a browser write agents/instances/<id>/. Everything the
rollout refuses at deploy time -- a missing tool list, an empty one, a skill
that does not exist -- must be refused at SAVE time too, or the form becomes a
way to prepare a rollout that cannot run. And two guarantees are new here:

  * limits borrowed with `same_as` resolve to the other agent's numbers, and a
    dangling or self-referential borrow is refused (the drift that once made a
    whole day's comparison unreadable)
  * deletion MOVES to .trash/, the roster no longer sees it, the rollout's plan
    reads the trash as intent, and an agent whose SOUL others link to cannot go

Offline and free: works on a temporary copy of agents/, touches no gateway.

Usage:
    PYTHONPATH=lib/mora02_core/src python3 tests/agents/test_builder_store.py
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib" / "mora02_core" / "src"))

from mora02_core.agents import deploy, store  # noqa: E402

results: list[tuple[str, str, str]] = []


def record(ok: bool, subject: str, detail: str = "") -> None:
    results.append(("PASS" if ok else "FAIL", subject, detail))
    print(f"[{'  ok  ' if ok else ' FAIL '}] {subject}{(': ' + detail) if detail else ''}")


def refuses(fn, subject: str, needle: str = "") -> None:
    try:
        fn()
    except store.StoreError as e:
        record(needle.lower() in str(e).lower() if needle else True, subject, str(e)[:90])
        return
    record(False, subject, "was accepted")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="agents-store-"))
    try:
        # Without the real .trash/: the API suite leaves its probe there, and a
        # copy that carries it would make the trash assertions below depend on
        # what some other suite did last.
        shutil.copytree(ROOT / "agents", tmp / "agents", symlinks=True,
                        ignore=shutil.ignore_patterns(".trash"))
        A = tmp / "agents"

        # --- reading the real roster through the copy ----------------------
        roster = store.load_roster(A)
        ids = [a["id"] for a in roster["agents"]]
        record("recherche" in ids and "main" in ids, "load_roster", ", ".join(ids))
        deploy.check_tools(roster)
        record(True, "check_tools accepts the shipped roster")

        d = store.instance_detail("recherche-plus", A)
        record(d["soul_shared_with"] == "recherche", "shared SOUL is read as a link", str(d["soul_shared_with"]))
        record(bool(d["soul"]), "shared SOUL text comes through the link")

        sk = {s["name"] for s in store.skills_catalog(A)}
        record("recherche" in sk, "skills_catalog", ", ".join(sorted(sk)))
        record(len(store.builtin_tools(A)) >= 10, "builtin_tools from tools.json", str(len(store.builtin_tools(A))))

        # --- creating one --------------------------------------------------
        base = {
            "label": "Probe", "icon": "x", "description": "d", "active": True,
            "model": "llama-local/qwen3-14b", "timeout": 60, "skills": ["recherche"],
            "tools": {"allow": ["read"]},
        }
        r = store.save_instance("zz-probe", dict(base), soul="# Probe\n", agents_dir=A)
        record(r["created"] and (A / "instances/zz-probe/agent.json").is_file()
               and (A / "instances/zz-probe/SOUL.md").read_text() == "# Probe\n",
               "save_instance creates folder, manifest and SOUL")
        saved = json.loads((A / "instances/zz-probe/agent.json").read_text())
        record("id" not in saved and "_dir" not in saved, "runtime fields never written to the file")

        before = (A / "instances/zz-probe/agent.json").read_bytes()
        store.save_instance("zz-probe", dict(base), soul="# Probe\n", agents_dir=A)
        record(before == (A / "instances/zz-probe/agent.json").read_bytes(), "saving twice is byte-identical (idempotent)")

        # --- what must be refused at save time ----------------------------
        refuses(lambda: store.save_instance("Bad Id", dict(base), agents_dir=A), "id with space refused", "id")
        refuses(lambda: store.save_instance("zz-p2", {**base, "tools": {"allow": []}}, agents_dir=A), "empty tool list refused", "empty")
        refuses(lambda: store.save_instance("zz-p2", {k: v for k, v in base.items() if k != "tools"}, agents_dir=A), "missing tool list refused", "tools.allow")
        refuses(lambda: store.save_instance("zz-p2", {**base, "skils": []}, agents_dir=A), "typo'd key refused", "unknown field")
        refuses(lambda: store.save_instance("zz-p2", {**base, "skills": ["nope"]}, agents_dir=A), "unknown skill refused", "does not exist")
        refuses(lambda: store.save_instance("zz-p2", {**base, "limits": {"page_chars": -1}}, agents_dir=A), "negative limit refused", "positive")
        refuses(lambda: store.save_instance("zz-p2", {**base, "limits": {"same_as": "zz-p2"}}, agents_dir=A), "same_as itself refused", "itself")
        refuses(lambda: store.save_instance("zz-p2", {**base, "limits": {"same_as": "ghost"}}, agents_dir=A), "same_as dangling refused", "does not exist")
        refuses(lambda: store.save_instance("zz-p2", {**base, "limits": {"same_as": "recherche", "page_chars": 1}}, agents_dir=A), "same_as plus own values refused", "drift")
        refuses(lambda: store.save_instance("main", {**base, "active": True}, agents_dir=A), "main cannot be made active", "letterbox")
        record(not (A / "instances/zz-p2").exists(), "a refused save leaves no folder behind")

        # --- borrowed limits -----------------------------------------------
        store.save_instance("zz-twin", {**base, "limits": {"same_as": "recherche"}}, soul="# T\n", agents_dir=A)
        eff = store.effective_limits(store.load_manifest("zz-twin", A), A)
        want = store.load_manifest("recherche", A)["limits"]
        record(eff == want, "same_as resolves to the other agent's limits", f"{len(eff or {})} values")
        entry = deploy.desired_agent_entry(store.load_roster(A)["agents"][[a["id"] for a in store.load_roster(A)["agents"]].index("zz-twin")])
        record("limits" not in entry and "timeout" not in entry, "limits and timeout stay out of the gateway entry")

        # a borrow that goes dangling later is caught on the next roster read
        (A / "instances/zz-twin/agent.json").write_text(json.dumps({**base, "limits": {"same_as": "ghost"}}))
        refuses(lambda: store.load_roster(A), "load_roster refuses a dangling same_as", "does not exist")
        (A / "instances/zz-twin/agent.json").write_text(json.dumps({**base, "limits": {"same_as": "recherche"}}))

        # --- shared SOUL ---------------------------------------------------
        store.save_instance("zz-twin", {**base, "limits": {"same_as": "recherche"}}, soul_shared_with="zz-probe", agents_dir=A)
        sp = A / "instances/zz-twin/SOUL.md"
        record(sp.is_symlink() and os.readlink(sp) == "../zz-probe/SOUL.md", "SOUL can be shared as a relative symlink")
        refuses(lambda: store.save_instance("zz-p3", dict(base), soul_shared_with="zz-twin", agents_dir=A), "sharing a shared SOUL refused", "original")
        refuses(lambda: store.save_instance("zz-p3", dict(base), soul="x", soul_shared_with="zz-probe", agents_dir=A), "soul and share together refused", "not both")
        store.save_instance("zz-twin", {**base, "limits": {"same_as": "recherche"}}, soul="# own\n", agents_dir=A)
        record(not sp.is_symlink() and sp.read_text() == "# own\n"
               and (A / "instances/zz-probe/SOUL.md").read_text() == "# Probe\n",
               "giving an own SOUL breaks the link without writing through it")

        files = deploy.desired_workspace_files(
            [a for a in store.load_roster(A)["agents"] if a["id"] == "zz-twin"][0], A)
        record(any(p.endswith("/SOUL.md") for p in files) and any("/skills/recherche/" in p for p in files),
               "workspace render carries SOUL and the granted skill", f"{len(files)} files")

        # --- deletion ------------------------------------------------------
        store.save_instance("zz-twin", {**base, "limits": {"same_as": "recherche"}}, soul_shared_with="zz-probe", agents_dir=A)
        refuses(lambda: store.trash_instance("zz-probe", A), "an agent lending its SOUL cannot be trashed", "lends")
        refuses(lambda: store.trash_instance("main", A), "main cannot be trashed", "cannot be deleted")
        mv = store.trash_instance("zz-twin", A)
        record(".trash/zz-twin-" in mv["moved_to"] and Path(mv["moved_to"]).is_dir(), "trash moves the folder", mv["moved_to"].rsplit("/", 1)[-1])
        record("zz-twin" not in [a["id"] for a in store.load_roster(A)["agents"]], "roster no longer sees a trashed agent")
        record(deploy.trashed_ids(A) == {"zz-twin"}, "trashed_ids reads the intent", str(deploy.trashed_ids(A)))
        mv2 = store.trash_instance("zz-probe", A)  # dependant is gone now
        record(deploy.trashed_ids(A) == {"zz-twin", "zz-probe"}, "two trashed agents, both read back")
        refuses(lambda: store.trash_instance("zz-probe", A), "trashing twice is a 'no agent'", "no agent")

        # --- a folder without a manifest is an error, not a skip ----------
        (A / "instances/zz-half").mkdir()
        refuses(lambda: store.load_roster(A), "instance folder without agent.json refused", "no agent.json")
        shutil.rmtree(A / "instances/zz-half")

        # --- a stale reference to a trashed agent surfaces ------------------
        (A / "instances/zz-p9").mkdir()
        (A / "instances/zz-p9/agent.json").write_text(json.dumps({**base, "limits": {"same_as": "zz-probe"}}))
        refuses(lambda: store.load_roster(A), "same_as to a trashed agent refused on read", "does not exist")

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    fails = [r for r in results if r[0] == "FAIL"]
    print(f"\n{len(results) - len(fails)} passed, {len(fails)} failed")
    for _, s, d in fails:
        print(f"  FAILED  {s}: {d}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
