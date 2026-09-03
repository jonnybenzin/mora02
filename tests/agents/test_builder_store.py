#!/usr/bin/env python3
"""Does the builder's store keep the promises the rollout relies on?

Increment 4 lets a browser write an agent folder. Everything the rollout
refuses at deploy time -- a missing tool list, an empty one, a skill that does
not exist -- must be refused at SAVE time too, or the form becomes a way to
prepare a rollout that cannot run. What this suite pins down:

  * one kind of agent, one place: data/agents/instances/. The platform root
    (agents/) ships skills, tools and the reception desk -- and no agents.
  * `main` is the reception desk, not an agent: configured in gateway.json,
    rendered by the rollout, refused as an agent id.
  * limits and SOUL may be borrowed by reference (`same_as`,
    `soul_shared_with`); a dangling or self-referential borrow is refused
  * deletion MOVES to .trash/; the rollout reads the trash as intent

Offline and free: builds its own fixtures in a temp directory, touches no
gateway and none of the machine's real agents.

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


BASE = {
    "label": "Probe", "icon": "x", "description": "d", "active": True,
    "model": "llama-local/current", "timeout": 60, "skills": ["recherche"],
    "tools": {"allow": ["read"]},
}
OWN_LIMITS = {"page_chars": 4000, "max_urls": 8, "max_queries": 8, "snippet_chars": 300,
              "results_per_query": 8, "max_pages_total": 24, "max_searches_total": 8}


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="agents-store-"))
    try:
        # platform = the repo's agents/ as shipped (no instances); local = empty
        shutil.copytree(ROOT / "agents", tmp / "agents", symlinks=True,
                        ignore=shutil.ignore_patterns(".trash"))
        (tmp / "data" / "agents" / "instances").mkdir(parents=True)
        (tmp / "data" / "agents" / "skills").mkdir(parents=True)
        P, L = tmp / "agents", tmp / "data" / "agents"
        RT = store.roots(P, L)
        NOLOCAL = store.roots(P)

        # --- the platform ships no agents, and a reception desk --------------
        record(not any((P / "instances").iterdir()) if (P / "instances").is_dir() else True,
               "agents/instances ships empty")
        r = store.load_roster(RT)
        record(r["agents"] == [], "empty roster is a legitimate state (fresh clone)")
        lb = r["letterbox"]
        record(bool(lb) and lb["id"] == "main" and lb["tools"]["allow"] and lb["manage_workspace"] is False,
               "reception desk read from gateway.json", str(lb and lb["tools"]["allow"]))
        deploy.check_tools(r)
        record(True, "check_tools covers the reception desk")

        sk = {s["name"]: s["root"] for s in store.skills_catalog(RT)}
        record(sk.get("recherche") == "platform" and sk.get("briefing") == "platform", "skills come from the platform", ", ".join(sorted(sk)))
        record(len(store.builtin_tools(RT)) >= 10, "builtin_tools from tools.json", str(len(store.builtin_tools(RT))))

        # --- main is not an agent -------------------------------------------------
        refuses(lambda: store.save_instance("main", dict(BASE), soul="x", rt=RT), "main refused as an agent id", "reception desk")
        (L / "instances/main").mkdir()
        (L / "instances/main/agent.json").write_text("{}")
        refuses(lambda: store.load_roster(RT), "an instances/main folder is refused", "not an agent")
        shutil.rmtree(L / "instances/main")
        refuses(lambda: store.save_instance("zz", dict(BASE), soul="x", rt=NOLOCAL), "no installation root -> cannot create", "no installation root")

        # --- creating agents --------------------------------------------------------
        r1 = store.save_instance("base-a", {**BASE, "limits": OWN_LIMITS}, soul="# Base A\n", rt=RT)
        record(r1["created"] and (L / "instances/base-a/agent.json").is_file()
               and (L / "instances/base-a/SOUL.md").read_text() == "# Base A\n",
               "save_instance creates folder, manifest and SOUL under data/agents/")
        saved = json.loads((L / "instances/base-a/agent.json").read_text())
        record("id" not in saved and "_dir" not in saved, "runtime fields never written to the file")
        before = (L / "instances/base-a/agent.json").read_bytes()
        store.save_instance("base-a", {**BASE, "limits": OWN_LIMITS}, soul="# Base A\n", rt=RT)
        record(before == (L / "instances/base-a/agent.json").read_bytes(), "saving twice is byte-identical (idempotent)")
        record([a["id"] for a in store.load_roster(RT)["agents"]] == ["base-a"], "roster sees it by existing")

        # --- what must be refused at save time ------------------------------
        refuses(lambda: store.save_instance("Bad Id", dict(BASE), rt=RT), "id with space refused", "id")
        refuses(lambda: store.save_instance("zz-p2", {**BASE, "tools": {"allow": []}}, rt=RT), "empty tool list refused", "empty")
        refuses(lambda: store.save_instance("zz-p2", {k: v for k, v in BASE.items() if k != "tools"}, rt=RT), "missing tool list refused", "tools.allow")
        refuses(lambda: store.save_instance("zz-p2", {**BASE, "skils": []}, rt=RT), "typo'd key refused", "unknown field")
        refuses(lambda: store.save_instance("zz-p2", {**BASE, "skills": ["nope"]}, rt=RT), "unknown skill refused", "does not exist")
        refuses(lambda: store.save_instance("zz-p2", {**BASE, "limits": {"page_chars": -1}}, rt=RT), "negative limit refused", "positive")
        refuses(lambda: store.save_instance("zz-p2", {**BASE, "limits": {"same_as": "zz-p2"}}, rt=RT), "same_as itself refused", "itself")
        refuses(lambda: store.save_instance("zz-p2", {**BASE, "limits": {"same_as": "ghost"}}, rt=RT), "same_as dangling refused", "does not exist")
        refuses(lambda: store.save_instance("zz-p2", {**BASE, "limits": {"same_as": "base-a", "page_chars": 1}}, rt=RT), "same_as plus own values refused", "drift")
        record(not (L / "instances/zz-p2").exists(), "a refused save leaves no folder behind")

        # --- model policy (ADR-029 point 6): steering or sensitive means local ----------
        CLOUD = "anthropic/claude-sonnet-4-6"
        refuses(lambda: store.save_instance("zz-l1", {**BASE, "model": CLOUD, "tools": {"allow": ["read", "exec"]}}, rt=RT),
                "cloud model with an acting gateway tool refused", "must run locally")
        refuses(lambda: store.save_instance("zz-l1", {**BASE, "model": CLOUD, "tools": {"allow": ["read", "mora02__flow_run"]}}, rt=RT),
                "cloud model with the MCP flow starter refused", "flow_run")
        refuses(lambda: store.save_instance("zz-l1", {**BASE, "model": CLOUD, "tools": "unrestricted"}, rt=RT),
                "cloud model with unrestricted tools refused", "unrestricted")
        refuses(lambda: store.save_instance("zz-l1", {**BASE, "model": CLOUD, "sensitive": True}, rt=RT),
                "cloud model on a sensitive agent refused", "sensitive")
        refuses(lambda: store.save_instance("zz-l1", {**BASE, "sensitive": "ja"}, rt=RT),
                "sensitive must be a boolean", "true or false")
        store.save_instance("zz-l2", {**BASE, "model": CLOUD, "tools": {"allow": ["read", "mora02__web_search", "mora02__note"]}}, rt=RT)
        record(store.load_manifest("zz-l2", RT)["model"] == CLOUD, "cloud model with reading tools only is allowed (the recherche-plus shape)")
        store.save_instance("zz-l3", {**BASE, "tools": {"allow": ["read", "exec", "mora02__flow_run"]}, "sensitive": True}, rt=RT)
        record(store.load_manifest("zz-l3", RT)["sensitive"] is True, "local model may steer and be sensitive")
        record(store.tool_risk("nobody-knows-this", RT) == "act", "an unknown tool id counts as acting")
        # the second door: a manifest written by hand, past the form
        (L / "instances/zz-l2/agent.json").write_text(json.dumps({**BASE, "model": CLOUD, "tools": {"allow": ["read", "exec"]}}))
        try:
            deploy.check_locality(store.load_roster(RT), RT)
            record(False, "rollout refuses a hand-written cloud+acting manifest", "was accepted")
        except deploy.DeployError as e:
            record("must" in str(e), "rollout refuses a hand-written cloud+acting manifest", str(e)[:80])
        for aid in ("zz-l2", "zz-l3"):
            shutil.rmtree(L / f"instances/{aid}")

        # --- borrowed limits ------------------------------------------------------------
        store.save_instance("twin", {**BASE, "limits": {"same_as": "base-a"}}, soul="# T\n", rt=RT)
        eff = store.effective_limits(store.load_manifest("twin", RT), RT)
        record(eff == OWN_LIMITS, "same_as resolves to the other agent's limits", f"{len(eff or {})} values")
        twin = [a for a in store.load_roster(RT)["agents"] if a["id"] == "twin"][0]
        entry = deploy.desired_agent_entry(twin)
        record("limits" not in entry and "timeout" not in entry and "soul_shared_with" not in entry,
               "limits, timeout and soul reference stay out of the gateway entry")
        (L / "instances/twin/agent.json").write_text(json.dumps({**BASE, "limits": {"same_as": "ghost"}}))
        refuses(lambda: store.load_roster(RT), "load_roster refuses a dangling same_as", "does not exist")

        # --- borrowed SOUL by reference -------------------------------------------------
        store.save_instance("twin", {**BASE, "limits": {"same_as": "base-a"}}, soul_shared_with="base-a", rt=RT)
        m = store.load_manifest("twin", RT)
        record(m.get("soul_shared_with") == "base-a" and not (L / "instances/twin/SOUL.md").exists(),
               "SOUL borrowed as a manifest reference, own file removed")
        d = store.instance_detail("twin", RT)
        record(d["soul_shared_with"] == "base-a" and d["soul"] == "# Base A\n", "detail resolves the borrowed SOUL text")
        files = deploy.desired_workspace_files([a for a in store.load_roster(RT)["agents"] if a["id"] == "twin"][0], RT)
        soul_key = [k for k in files if k.endswith("/SOUL.md")]
        record(bool(soul_key) and files[soul_key[0]] == "# Base A\n" and any("/skills/recherche/" in k for k in files),
               "rollout renders the borrowed SOUL and the platform skill", f"{len(files)} files")
        refuses(lambda: store.save_instance("zz-p3", dict(BASE), soul_shared_with="twin", rt=RT), "borrowing from a borrower refused", "original")
        refuses(lambda: store.save_instance("zz-p3", dict(BASE), soul_shared_with="zz-p3", rt=RT), "borrowing from itself refused", "itself")
        refuses(lambda: store.save_instance("zz-p3", dict(BASE), soul="x", soul_shared_with="base-a", rt=RT), "soul and share together refused", "not both")
        store.save_instance("twin", {**BASE, "limits": {"same_as": "base-a"}}, soul="# own\n", rt=RT)
        m = store.load_manifest("twin", RT)
        record("soul_shared_with" not in m and (L / "instances/twin/SOUL.md").read_text() == "# own\n"
               and (L / "instances/base-a/SOUL.md").read_text() == "# Base A\n",
               "giving an own SOUL drops the reference without touching the original")

        # the legacy form: a symlink SOUL is still read as a borrow
        (L / "instances/twin/SOUL.md").unlink()
        os.symlink("../base-a/SOUL.md", L / "instances/twin/SOUL.md")
        d = store.instance_detail("twin", RT)
        record(d["soul_shared_with"] == "base-a" and d["soul"] == "# Base A\n", "legacy symlink SOUL is read as a borrow")
        store.save_instance("twin", {**BASE, "limits": {"same_as": "base-a"}}, soul="# own\n", rt=RT)
        record(not (L / "instances/twin/SOUL.md").is_symlink() and (L / "instances/base-a/SOUL.md").read_text() == "# Base A\n",
               "writing over a legacy symlink breaks it instead of writing through")

        # --- the other workspace files + reading a skill -------------------------
        store.save_instance("twin", {**BASE, "limits": {"same_as": "base-a"}}, files={"USER.md": "likes short answers"}, rt=RT)
        record((L / "instances/twin/USER.md").read_text() == "likes short answers\n"
               and store.instance_detail("twin", RT)["files"] == {"USER.md": "likes short answers\n"},
               "extra workspace file written and read back")
        files = deploy.desired_workspace_files([a for a in store.load_roster(RT)["agents"] if a["id"] == "twin"][0], RT)
        record(any(p.endswith("/USER.md") for p in files), "the rollout renders it (one list, two readers)")
        store.save_instance("twin", {**BASE, "limits": {"same_as": "base-a"}}, files={"USER.md": ""}, rt=RT)
        record(not (L / "instances/twin/USER.md").exists(), "empty string removes the file")

        # the shared USER.md of the installation: every workspace gets it, an own one wins
        def _user_md():
            f = deploy.desired_workspace_files([a for a in store.load_roster(RT)["agents"] if a["id"] == "twin"][0], RT)
            hit = [v for k, v in f.items() if k.endswith("/USER.md")]
            return hit[0] if hit else None
        record(_user_md() is None, "no USER.md anywhere: none rendered")
        (L / "USER.md").write_text("# The person\nwrites German\n")
        record(_user_md() == "# The person\nwrites German\n", "data/agents/USER.md is rendered into a workspace without its own")
        store.save_instance("twin", {**BASE, "limits": {"same_as": "base-a"}}, files={"USER.md": "own view"}, rt=RT)
        record(_user_md() == "own view\n", "an agent's own USER.md overrides the shared one")
        store.save_instance("twin", {**BASE, "limits": {"same_as": "base-a"}}, files={"USER.md": ""}, rt=RT)
        (L / "USER.md").unlink()
        refuses(lambda: store.save_instance("twin", {**BASE, "limits": {"same_as": "base-a"}}, files={"EVIL.md": "x"}, rt=RT),
                "a file outside the allowed set is refused", "not a workspace file")

        sd = store.skill_detail("briefing", RT)
        paths = [f["path"] for f in sd["files"]]
        record("recherche/FRAGEN.md" in paths and all("content" in f for f in sd["files"]) and sd["root"] == "platform",
               "skill_detail lists the catalogue with content", ", ".join(paths))
        record(sd["used_by"] == [], "skill_detail names who uses it (nobody here)")
        refuses(lambda: store.skill_detail("../instances", RT), "skill_detail refuses a path", "no skill")
        refuses(lambda: store.skill_detail("nope", RT), "skill_detail unknown", "no skill")

        # a skill of the installation's own: found, usable, marked, no clash allowed
        (L / "skills/haus").mkdir()
        (L / "skills/haus/SKILL.md").write_text("---\nname: haus\ndescription: Use this when asked about the house.\n---\n# Haus\n")
        record({s["name"]: s["root"] for s in store.skills_catalog(RT)}.get("haus") == "local", "own skill appears in the catalogue")
        store.save_instance("twin", {**BASE, "limits": {"same_as": "base-a"}, "skills": ["recherche", "haus"]}, rt=RT)
        files = deploy.desired_workspace_files([a for a in store.load_roster(RT)["agents"] if a["id"] == "twin"][0], RT)
        record(any("/skills/haus/SKILL.md" in p for p in files) and any("/skills/recherche/" in p for p in files),
               "rollout renders skills from both roots")
        (P / "skills/haus").mkdir()
        (P / "skills/haus/SKILL.md").write_text("---\nname: haus\n---\n")
        refuses(lambda: store.skills_catalog(RT), "same skill in both roots refused", "both")
        shutil.rmtree(P / "skills/haus")

        # --- deletion ----------------------------------------------------------
        store.save_instance("twin", {**BASE, "limits": {"same_as": "base-a"}}, soul_shared_with="base-a", rt=RT)
        refuses(lambda: store.trash_instance("base-a", RT), "an agent lending its SOUL cannot be trashed", "lends")
        refuses(lambda: store.trash_instance("main", RT), "main cannot be trashed (it is not an agent)", "no agent")
        mv = store.trash_instance("twin", RT)
        record("/instances/.trash/twin-" in mv["moved_to"] and Path(mv["moved_to"]).is_dir(), "trash moves the folder", mv["moved_to"].rsplit("/", 1)[-1])
        record([a["id"] for a in store.load_roster(RT)["agents"]] == ["base-a"], "roster no longer sees a trashed agent")
        record(deploy.trashed_ids(RT) == {"twin"}, "trashed_ids reads the intent", str(deploy.trashed_ids(RT)))
        store.trash_instance("base-a", RT)
        record(deploy.trashed_ids(RT) == {"twin", "base-a"}, "two trashed agents, both read back")
        refuses(lambda: store.trash_instance("twin", RT), "trashing twice is a 'no agent'", "no agent")

        # --- the per-agent model catalog follows the config -----------------------
        cfg = {"providers": {"llama-local": {"baseUrl": "http://llama-server:8080/v1", "api": "openai-completions",
                                             "apiKey": "__OPENCLAW_REDACTED__",
                                             "models": [{"id": "current", "contextWindow": 131072}]}}}
        stale = {"providers": {"llama-local": {"baseUrl": "x", "apiKey": "sk-dummy",
                                               "models": [{"id": "qwen3-14b", "contextWindow": 128000}]}}}
        want = deploy.desired_catalog(cfg, stale)
        m = want["providers"]["llama-local"]
        record(m["models"] == [{"id": "current", "contextWindow": 131072}] and m["baseUrl"].endswith("/v1"),
               "catalog takes models and baseUrl from the config")
        record(m["apiKey"] == "sk-dummy", "redacted key: the existing catalog's key is kept")
        record("apiKey" not in deploy.desired_catalog(cfg, None)["providers"]["llama-local"],
               "redacted key and no catalog: the field is left out, never the marker")
        record(deploy.desired_catalog(cfg, want) == want, "rendering is idempotent")

        # --- a folder without a manifest is an error, not a skip --------------
        (L / "instances/zz-half").mkdir()
        refuses(lambda: store.load_roster(RT), "instance folder without agent.json refused", "no agent.json")
        shutil.rmtree(L / "instances/zz-half")

        # --- stale references to a trashed agent surface -----------------------
        (L / "instances/zz-p9").mkdir()
        (L / "instances/zz-p9/agent.json").write_text(json.dumps({**BASE, "limits": {"same_as": "base-a"}}))
        refuses(lambda: store.load_roster(RT), "same_as to a trashed agent refused on read", "does not exist")
        (L / "instances/zz-p9/agent.json").write_text(json.dumps({**BASE, "soul_shared_with": "twin"}))
        refuses(lambda: store.load_roster(RT), "soul_shared_with to a trashed agent refused on read", "no soul.md")

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    fails = [r for r in results if r[0] == "FAIL"]
    print(f"\n{len(results) - len(fails)} passed, {len(fails)} failed")
    for _, s, d in fails:
        print(f"  FAILED  {s}: {d}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
