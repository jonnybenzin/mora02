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
import re
import shlex
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib" / "mora02_core" / "src"))

from mora02_core.agents import cli, deploy, store  # noqa: E402

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

        # --- paths that reach a shell in the gateway (review A1, 2026-09-03) ----
        # The workspace is bound to the id: any other value is refused at the
        # form and again on every read of the roster (the hand-written door).
        refuses(lambda: store.save_instance("zz-ws", {**BASE, "workspace": "/tmp/x; echo pwned"}, rt=RT),
                "crafted workspace refused at save time", "workspace must be")
        store.save_instance("zz-ws", {**BASE, "workspace": store.default_workspace("zz-ws")}, soul="x", rt=RT)
        record(store.load_manifest("zz-ws", RT)["workspace"] == "/data/openclaw/agents/zz-ws/workspace",
               "the agent's own workspace path is accepted")
        (L / "instances/zz-ws/agent.json").write_text(json.dumps({**BASE, "workspace": "/data/openclaw/agents/other/workspace"}))
        refuses(lambda: store.load_roster(RT), "hand-written foreign workspace refused on read", "workspace must be")
        shutil.rmtree(L / "instances/zz-ws")
        # A skill file whose name carries a space and parentheses must reach the
        # shell as ONE word. The command string is inspected, never executed.
        sk_dir = L / "skills" / "zz-quote"
        sk_dir.mkdir(parents=True)
        (sk_dir / "SKILL.md").write_text("---\nname: zz-quote\ndescription: probe\n---\n# q\n")
        (sk_dir / "Fragen (alt).md").write_text("# alt\n")
        store.save_instance("zz-q", {**BASE, "skills": ["zz-quote"]}, soul="x", rt=RT)
        agent = next(a for a in store.load_roster(RT)["agents"] if a["id"] == "zz-q")
        odd = [p for p in deploy.desired_workspace_files(agent, RT) if "Fragen (alt)" in p]
        record(len(odd) == 1, "skill file with a space is part of the rollout", odd[0] if odd else "missing")
        seen: list[list[str]] = []
        real_docker = deploy.docker
        deploy.docker = lambda *argv, stdin=None: (seen.append(list(argv)), (0, ""))[1]
        try:
            deploy.write_remote(odd[0], "x")
            deploy.remote_file(odd[0])
            deploy.write_remote("/tmp/x; echo pwned", "x")
        finally:
            deploy.docker = real_docker
        cmds = [argv[-1] for argv in seen if argv[:2] == ["sh", "-c"]]
        record(len(cmds) == 3 and all(odd[0] in shlex.split(c) for c in cmds[:2]),
               "write and read pass the odd path to the shell as one word", cmds[0][:70] if cmds else "")
        record(len(cmds) == 3 and "/tmp/x; echo pwned" in shlex.split(cmds[2]) and ";" not in shlex.split(cmds[2])[:3],
               "a crafted path is one word to the shell, not three commands", cmds[2][:70] if len(cmds) > 2 else "")
        shutil.rmtree(L / "instances/zz-q"); shutil.rmtree(sk_dir)

        # audit 2026-09-04: agentDir is a path too, and load_roster does not
        # validate manifests -- so it needs the same pin as workspace.
        refuses(lambda: store.save_instance("zz-ad", {**BASE, "agentDir": "/data/openclaw"}, rt=RT),
                "agentDir refused at save time", "unknown field")
        store.save_instance("zz-ad", dict(BASE), soul="x", rt=RT)
        (L / "instances/zz-ad/agent.json").write_text(json.dumps({**BASE, "agentDir": "/data/openclaw"}))
        refuses(lambda: store.load_roster(RT), "hand-written agentDir refused on read", "gateway's to set")
        shutil.rmtree(L / "instances/zz-ad")

        # --- section C of the review: design ---------------------------------------
        record(store.tool_risk("mora02__nobody-classified-this", RT) == "act", "C an unclassified MCP tool counts as acting")
        record(store.tool_risk("mora02__web_read", RT) == "read" and store.mcp_tool_risk("flow_run") == "act",
               "C the known MCP tools keep their reading / acting")
        gw = P / "gateway.json"
        gw_before = gw.read_text()
        try:
            desk = json.loads(gw_before)
            desk["letterbox"]["tools"] = {"allow": ["read", "exec"]}
            gw.write_text(json.dumps(desk))
            try:
                deploy.check_locality(store.load_roster(RT), RT)
                record(False, "C a steering reception desk without a model is refused", "was accepted")
            except deploy.DeployError as e:
                record("reception desk" in str(e) and "names no model" in str(e), "C a steering reception desk without a model is refused", str(e)[:80])
            desk["letterbox"]["model"] = "anthropic/claude-sonnet-4-6"
            gw.write_text(json.dumps(desk))
            refused = False
            try:
                deploy.check_locality(store.load_roster(RT), RT)
            except deploy.DeployError as e:
                refused = "reception desk" in str(e) and "not local" in str(e)
            record(refused, "C a steering reception desk on a cloud model is refused")
            desk["letterbox"]["model"] = "llama-local/current"
            gw.write_text(json.dumps(desk))
            deploy.check_locality(store.load_roster(RT), RT)
            record(True, "C a steering reception desk on a local model passes")
        finally:
            gw.write_text(gw_before)
        deploy.check_locality(store.load_roster(RT), RT)
        record(True, "C the shipped reception desk (reading tools, no model) passes")

        # --- group B (review 2026-09-03, findings 5-10) --------------------------------
        # A stand-in for docker(): records every call, answers by substring, and
        # says (0, "") to everything else -- so remote_file() reads "absent".
        def fake(answers):
            def _docker(*argv, stdin=None):
                calls.append((list(argv), stdin))
                for needle, reply in answers:
                    if needle in " ".join(argv):
                        return reply
                return (0, "")
            return _docker
        calls: list = []
        # B5: the kill pattern ends this session's turn and no other
        pat = cli.kill_pattern("agent:x:1")
        line = "openclaw agent --agent x --session-key agent:x:1 --message hi"
        record(bool(re.search(pat, line)) and not re.search(pat, line.replace("agent:x:1", "agent:x:10")),
               "B5 kill pattern matches session 1 and not session 10", pat)
        record(not re.search(cli.kill_pattern("agent:x:1.2"), line.replace("agent:x:1", "agent:x:1x2")),
               "B5 a dot in the key is a dot, not a wildcard")

        # B10: a folder whose name is not an id never reaches the gateway --
        # but it takes nothing else down with it (audit, 2026-09-04: raising in
        # iter_instances broke the chat's agent list, delete and the skill pages).
        (L / "instances/Recherche_DE").mkdir()
        (L / "instances/Recherche_DE/agent.json").write_text(json.dumps(BASE))
        record(store.stray_instance_names(RT) == ["Recherche_DE"], "B10 a folder that cannot be an id is named")
        record("Recherche_DE" not in [f.name for f in store.iter_instances(RT)], "B10 ... skipped when listing")
        refuses(lambda: store.load_roster(RT), "B10 ... and refused by the rollout", "not a valid agent id")
        record(store.skill_detail("recherche", RT)["name"] == "recherche",
               "B10 the skill pages keep working beside it")
        store.save_instance("zz-b10", dict(BASE), soul="x", rt=RT)
        mv = store.trash_instance("zz-b10", RT)
        record(".trash/zz-b10-" in mv["moved_to"], "B10 deleting an agent keeps working beside it")
        shutil.rmtree(L / "instances/Recherche_DE")

        # B6: the platform's trash is not intent, and a carried-out deletion is spent
        (P / "instances/.trash/zz-old-20260101000000").mkdir(parents=True)
        record("zz-old" not in deploy.trashed_ids(RT), "B6 platform trash is not read as intent")
        shutil.rmtree(P / "instances/.trash")
        store.save_instance("zz-gone", dict(BASE), soul="x", rt=RT)
        store.trash_instance("zz-gone", RT)
        record("zz-gone" in deploy.trashed_ids(RT), "B6 trashed agent is intent before the rollout")
        deploy.mark_trash_applied(RT, "zz-gone")
        record("zz-gone" not in deploy.trashed_ids(RT), "B6 ... and spent once the gateway forgot it")
        record(any((f / deploy.TRASH_APPLIED).is_file() for f in (L / "instances/.trash").iterdir() if f.name.startswith("zz-gone-")),
               "B6 the marker lives in the trash folder")

        # B6/B7/B8 as the plan sees them: a gateway with a hand-made agent, a
        # trashed one, and a roster agent that is not in the gateway yet.
        store.save_instance("zz-new", dict(BASE), soul="# new\n", rt=RT)
        store.save_instance("zz-live", dict(BASE), soul="# live\n", rt=RT)
        store.save_instance("zz-doomed", dict(BASE), soul="x", rt=RT)
        store.trash_instance("zz-doomed", RT)
        LIVE = {"list": [{"id": "main"}, {"id": "zz-live", "agentDir": "/x/zz-live"}, {"id": "hand-made"}, {"id": "zz-doomed"}]}
        roster = store.load_roster(RT)
        real_docker = deploy.docker
        try:
            deploy.docker = fake([("config get agents", (0, json.dumps(LIVE)))])
            pl = deploy.plan(roster, None, RT)
            ids = [e["id"] for e in pl.agents_block["list"]]
            record(any("hand-made" in n and "left alone" in n for n in pl.notes) and not any("hand-made" in d for d in pl.drift),
                   "B7 a hand-made gateway agent is a note, not drift", "; ".join(pl.notes)[:70])
            record("hand-made" in ids and "zz-doomed" not in ids and pl.remove == ["zz-doomed"],
                   "B6 full run: hand-made kept in the list, trashed one removed", str(ids))
            pl = deploy.plan(roster, "zz-new", RT)
            ids = [e["id"] for e in pl.agents_block["list"]]
            record(pl.remove == [] and "zz-doomed" in ids and "hand-made" in ids,
                   "B6 --agent zz-new deletes nothing and keeps every stray in the list", str(ids))
            record("zz-new" in ids and any("agent/zz-new: does not exist" in d for d in pl.drift),
                   "B8 the agent of the run is rendered and reported")
            # B6 (audit 2026-09-04): --agent may name an agent only the trash
            # still knows -- otherwise the one path that deletes one agent was
            # unreachable, because the roster no longer holds the name.
            pl = deploy.plan(roster, "zz-doomed", RT)
            record(pl.remove == ["zz-doomed"], "B6 --agent on a trashed agent removes exactly it", str(pl.remove))
            try:
                deploy.plan(roster, "never-existed", RT)
                record(False, "B6 --agent on an unknown id is still refused", "was accepted")
            except deploy.DeployError as e:
                record("in either root" in str(e), "B6 --agent on an unknown id is still refused")
            pl = deploy.plan(roster, "zz-live", RT)
            ids = [e["id"] for e in pl.agents_block["list"]]
            record("zz-new" not in ids and not any("zz-new" in d for d in pl.drift),
                   "B8 --agent zz-live leaves an uncreated zz-new out of the list", str(ids))

            # B9: files the last rollout wrote and this one no longer renders
            ws = "/data/openclaw/agents/zz-new/workspace"
            answers = [("config get agents", (0, json.dumps(LIVE))),
                       (f"cat {ws}/{deploy.RENDERED_RECORD}", (0, "SOUL.md\nskills/old/SKILL.md\nskills/old/Fragen (alt).md\n"))]
            deploy.docker = fake(answers)
            pl = deploy.plan(roster, "zz-new", RT)
            record(sorted(pl.stale) == [f"{ws}/skills/old/Fragen (alt).md", f"{ws}/skills/old/SKILL.md"],
                   "B9 files in the record but not rendered any more are stale", str(len(pl.stale)))
            rec_path, _ = deploy.rendered_record(ws, set())
            record(rec_path in pl.files and "SOUL.md\n" in pl.files[rec_path] and "skills/old" not in pl.files[rec_path],
                   "B9 the record is rewritten to what is rendered now", pl.files.get(rec_path, "")[:40].replace("\n", "|"))
            deploy.docker = fake([("config get agents", (0, json.dumps(LIVE)))])
            pl = deploy.plan(roster, "zz-new", RT)
            record(pl.stale == [] and any(d.startswith("record/zz-new") for d in pl.drift),
                   "B9 no record yet: nothing is removed, the record is announced")
            calls.clear()
            deploy.docker = fake([])
            deploy.apply(roster, deploy.Plan(agents_block={"list": []}, stale=[f"{ws}/skills/old/Fragen (alt).md"]), None, RT, lambda _l: None)
            rm = [" ".join(a) for a, _ in calls if a[:2] == ["sh", "-c"] and "rm -f" in a[-1]]
            record(len(rm) == 1 and f"{ws}/skills/old/Fragen (alt).md" in shlex.split(rm[0].split("rm -f", 1)[1].split("&&")[0]),
                   "B9 apply removes a stale file, quoted", rm[0][6:70] if rm else "no rm")
            record(bool(rm) and "exit 0" not in rm[0] and "|| true" in rm[0],
                   "B9 a failing rm is still an error (only the rmdir may fail)")

            # B9 hardening (audit 2026-09-04): the record lives in the agent's
            # own workspace, so its contents are agent-controlled input.
            record(deploy.workspace_path(ws, "skills/a/SKILL.md") == f"{ws}/skills/a/SKILL.md",
                   "B9 a plain relative entry resolves inside the workspace")
            record(all(deploy.workspace_path(ws, r) is None for r in
                       ("../../../openclaw.json", "/etc/passwd", "a/../../b", "", "..")),
                   "B9 an entry that leaves the workspace resolves to nothing")
            deploy.docker = fake([("config get agents", (0, json.dumps(LIVE))),
                                  (f"cat {ws}/{deploy.RENDERED_RECORD}",
                                   (0, "SOUL.md\n../../../openclaw.json\n"))])
            pl = deploy.plan(roster, "zz-new", RT)
            record(pl.stale == [] and any("is not a file in this workspace" in d for d in pl.drift),
                   "B9 a crafted record entry is named and NOT removed",
                   next((d for d in pl.drift if "not a file" in d), "")[:60])
            calls.clear()
            deploy.docker = fake([])
            deploy.apply(roster, deploy.Plan(agents_block={"list": []}, remove=["zz-doomed"]), None, RT, lambda _l: None)
            record("zz-doomed" not in deploy.trashed_ids(RT), "B6 apply marks the trash once the gateway deleted the agent")

            # A3 (live 2026-09-04): the gateway refuses a list that drops an
            # entry it still has, and at dry-run time the agents this run
            # deletes are still there. So the dry run shows it a list that
            # removes nothing, and the REAL patch writes the smaller one.
            # (The apply above spent the trash; unspend it for this case.)
            for _f in (L / "instances/.trash").iterdir():
                if _f.name.startswith("zz-doomed-"):
                    (_f / deploy.TRASH_APPLIED).unlink(missing_ok=True)
            deploy.docker = fake([("config get agents", (0, json.dumps(LIVE)))])
            pl = deploy.plan(roster, None, RT)
            dry_ids = [e["id"] for e in pl.dry_block["list"]]
            real_ids = [e["id"] for e in pl.agents_block["list"]]
            record("zz-doomed" in dry_ids and "zz-doomed" not in real_ids and pl.remove == ["zz-doomed"],
                   "A3 the dry-run list keeps what the real one drops", str(dry_ids))
            record(set(e["id"] for e in LIVE["list"]) <= set(dry_ids),
                   "A3 the dry-run list removes nothing the gateway has")
            calls.clear()
            deploy.docker = fake([])
            deploy.apply(roster, pl, None, RT, lambda _l: None)
            sent = [stdin for argv, stdin in calls if "--dry-run" in " ".join(argv)]
            real = [stdin for argv, stdin in calls
                    if "config patch" in " ".join(argv) and "--dry-run" not in " ".join(argv)]
            record(sent and "zz-doomed" in sent[0] and real and "zz-doomed" not in real[0],
                   "A3 apply dry-runs the wider list and writes the narrower one")
        finally:
            deploy.docker = real_docker
        for aid in ("zz-new", "zz-live"):
            shutil.rmtree(L / f"instances/{aid}")

        # --- the gateway's answers are read, not guessed (review A2) --------------
        # The CLI prints a warning line AFTER its JSON; the old reader turned
        # that into {} and planned every rollout against an empty gateway.
        real_docker = deploy.docker
        LIVE = '{"list": [{"id": "main"}, {"id": "hand-made"}]}\nWarning: Detected unsettled top-level await\n'
        try:
            deploy.docker = fake([("config get agents", (0, LIVE))])
            got = deploy._config_key("agents")
            record([a["id"] for a in got.get("list", [])] == ["main", "hand-made"],
                   "JSON followed by a warning line is read whole", str(got)[:60])
            deploy.docker = fake([("config get agents", (0, "Warning: {broken\n"))])
            try:
                deploy._config_key("agents"); record(False, "unreadable object is an error, not {}", "returned")
            except deploy.DeployError as e:
                record("unreadable" in str(e), "unreadable object is an error, not {}", str(e)[:70])
            deploy.docker = fake([("config get mcp", (1, "not set"))])
            record(deploy._config_key("mcp") == {}, "a key the gateway does not carry reads as {}")
            deploy.docker = fake([("config get agents", (1, "boom"))])
            try:
                deploy.read_config(); record(False, "unreadable agents section is fatal", "returned")
            except deploy.DeployError as e:
                record("could not read" in str(e), "unreadable agents section is fatal", str(e)[:60])
            calls.clear()
            deploy.docker = fake([("config get", (0, "{}"))])
            deploy.read_config()
            record(sum("config get agents" in " ".join(a) for a, _ in calls) == 1, "agents section is fetched once, not twice")

            # --- nothing is deleted before the gateway has validated the list (review A3) --
            calls.clear()
            deploy.docker = fake([("--dry-run", (1, "schema: agents.list[1].name must be a string"))])
            try:
                deploy.apply({"agents": []}, deploy.Plan(agents_block={"list": []}, remove=["doomed"]), None, RT, lambda _l: None)
                record(False, "a refused dry run stops the rollout", "apply returned")
            except deploy.DeployError as e:
                record("before anything was changed" in str(e), "a refused dry run stops the rollout", str(e)[:70])
            flat = [" ".join(a) for a, _ in calls]
            record(flat and "--dry-run" in flat[0] and not any("agents delete" in c for c in flat),
                   "dry run is the first call and no delete follows a refusal", str(len(flat)) + " call(s)")
            calls.clear()
            deploy.docker = fake([])
            deploy.apply({"agents": []}, deploy.Plan(agents_block={"list": []}, remove=["doomed"]), None, RT, lambda _l: None)
            flat = [" ".join(a) for a, _ in calls]
            i_dry = next(i for i, c in enumerate(flat) if "--dry-run" in c)
            i_del = next(i for i, c in enumerate(flat) if "agents delete doomed" in c)
            i_patch = next(i for i, c in enumerate(flat) if "config patch --stdin" in c and "--dry-run" not in c)
            record(i_dry < i_del < i_patch, "accepted dry run: delete, then the real patch", " -> ".join(c[9:40] for c in flat))
        finally:
            deploy.docker = real_docker

        # --- one list of limits (review 2, section E) -------------------------------
        import importlib
        _m = importlib.import_module("mcp_tools") if "mcp_tools" in sys.modules else None
        record(store.LIMIT_KEYS == frozenset(store.LIMIT_DEFAULTS) == frozenset(store.LIMITS),
               "keys, defaults and descriptions are the same seven")
        record(all(isinstance(v.get("default"), int) and v.get("help") for v in store.LIMITS.values()),
               "every limit carries a default and words for a person")
        store.save_instance("zz-lim", {**BASE, "limits": {"page_chars": 9000}}, soul="x", rt=RT)
        record(store.effective_limits(store.load_manifest("zz-lim", RT), RT)["page_chars"] == 9000,
               "an agent's own value wins over the default")
        refuses(lambda: store.save_instance("zz-lim", {**BASE, "limits": {"note_chars": 400}}, rt=RT),
                "a limit nobody defined is still refused", "unknown limit")
        shutil.rmtree(L / "instances/zz-lim")

        # --- one price table (review 2, section E) ----------------------------------
        from mora02_core import pricing as _pricing
        from mora02_core.llm.models import MODELS as _MODELS
        drift_rows = [(e["name"], e["cost_input_per_1m"], _pricing.rate_for(e["name"]))
                      for e in _MODELS.values()]
        record(all((r is None and ci == 0.0) or (r and ci == r[0]) for _n, ci, r in drift_rows),
               "the registry's prices come from the one table", str(len(drift_rows)) + " models")
        record(_pricing.rate_for("claude-sonnet-4-6") == (3.00, 15.00),
               "the model the manifests actually name is priced")
        record(_pricing.rate_for("nobody-priced-this") is None
               and _pricing.usd_last_call("nobody-priced-this", tokens_in=1000) is None,
               "an unpriced model reports no cost rather than a guessed one")
        exp = (1 / 1e6) * 3.0 + (50000 / 1e6) * 3.0 * _pricing.CACHE_READ_SHARE + (3031 / 1e6) * 15.0
        got = _pricing.usd_last_call("claude-sonnet-4-6", tokens_in=1, tokens_out=3031,
                                     tokens_cache_read=50000)
        record(abs(got - exp) < 1e-9, "a cache-heavy call is priced with the cache share",
               f"{got:.6f} USD")

        # --- a failure says what kind it is (review 2, section D) -------------------
        def kind(fn):
            try:
                fn()
            except store.StoreError as e:
                return type(e).__name__
            return "no error"
        record(kind(lambda: store.instance_detail("nobody", RT)) == "NotFound",
               "an agent that is not there is NotFound",
               kind(lambda: store.instance_detail("nobody", RT)))
        record(store.load_manifest("nobody", RT) == {},
               "load_manifest still answers {} rather than raising (it hides a broken one)")
        record(kind(lambda: store.skill_detail("nothing", RT)) == "NotFound",
               "a skill that is not there is NotFound")
        record(kind(lambda: store.save_instance("zz-k", dict(BASE), rt=NOLOCAL)) == "NoRoot",
               "no installation root is NoRoot")
        record(kind(lambda: store.save_instance("zz-k", {**BASE, "skils": []}, rt=RT)) == "Invalid",
               "a manifest the store refuses is Invalid")
        record(all(issubclass(c, store.StoreError) for c in (store.NotFound, store.Invalid, store.NoRoot)),
               "all three are still a StoreError for callers that only know that")

        # --- a refused save changes nothing (review 2, finding 8) -------------------
        store.save_instance("zz-half-save", dict(BASE), soul="# one\n", rt=RT)
        keep_m = (L / "instances/zz-half-save/agent.json").read_bytes()
        keep_s = (L / "instances/zz-half-save/SOUL.md").read_bytes()
        for bad, why in ((None, "null"), (42, "a number"), ({"a": 1}, "an object")):
            refuses(lambda b=bad: store.save_instance(
                "zz-half-save", {**BASE, "label": "CHANGED"}, soul="# two\n",
                files={"TOOLS.md": b}, rt=RT), f"a workspace file that is {why} is refused", "is text")
        record(keep_m == (L / "instances/zz-half-save/agent.json").read_bytes()
               and keep_s == (L / "instances/zz-half-save/SOUL.md").read_bytes(),
               "and the manifest and SOUL are exactly as they were")
        store.save_instance("zz-half-save", dict(BASE), files={"TOOLS.md": "notes\n"}, rt=RT)
        record((L / "instances/zz-half-save/TOOLS.md").read_text() == "notes\n",
               "a workspace file that IS text still lands")
        shutil.rmtree(L / "instances/zz-half-save")

        # --- an unreachable gateway is not an unfit roster (review 2, finding 5) ----
        store.save_instance("zz-gw", dict(BASE), soul="x", rt=RT)
        try:
            deploy.docker = fake([("config get agents", (1, "Cannot connect to the Docker daemon"))])
            res = deploy.run(check=True, rt=RT)
            record(res["error_kind"] == "gateway" and not res["ok"],
                   "a gateway that cannot be read is reported as a gateway problem",
                   f'{res["error_kind"]}: {str(res["error"])[:70]}')
            record(isinstance(deploy.GatewayError("x"), deploy.DeployError),
                   "a gateway problem is still a deploy problem for every old caller")
        finally:
            deploy.docker = real_docker
        (L / "instances/zz-broken").mkdir()
        (L / "instances/zz-broken/agent.json").write_text("{ not json")
        res = deploy.run(check=True, rt=RT)
        record(res["error_kind"] == "roster" and not res["ok"],
               "a roster nobody can read is reported as a roster problem", str(res["error_kind"]))
        shutil.rmtree(L / "instances/zz-broken")
        shutil.rmtree(L / "instances/zz-gw")

        # --- a root that is not there is no root (review A4) ------------------------
        env_before = os.environ.get("MORA02_AGENTS_LOCAL_DIR")
        os.environ["MORA02_AGENTS_LOCAL_DIR"] = str(tmp / "never-mounted")
        try:
            record(store.roots().local is None, "MORA02_AGENTS_LOCAL_DIR pointing nowhere reads as no root")
        finally:
            if env_before is None:
                os.environ.pop("MORA02_AGENTS_LOCAL_DIR", None)
            else:
                os.environ["MORA02_AGENTS_LOCAL_DIR"] = env_before
        empty = tmp / "empty-root"
        (empty / "instances").mkdir(parents=True)
        deploy.docker = lambda *a, stdin=None: (_ for _ in ()).throw(AssertionError("gateway touched"))
        try:
            res = deploy.run(check=True, rt=store.roots(P, empty))
            record(not res["ok"] and "no agents found" in (res["error"] or ""), "empty roster is refused before the gateway is read", str(res["error"])[:60])
            res = deploy.run(check=True, rt=NOLOCAL)
            record(not res["ok"] and "no installation root" in (res["error"] or ""), "no root at all is refused with its name", str(res["error"])[:60])
        finally:
            deploy.docker = real_docker

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
