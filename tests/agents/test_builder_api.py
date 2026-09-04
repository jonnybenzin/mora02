#!/usr/bin/env python3
"""The builder's HTTP surface, against the running script-runner.

What a browser needs to make an agent without a terminal: the parts list
(models from the gateway, skills, tools with their risk), one agent in full,
a save that is refused for the same reasons the rollout would refuse it, a
delete that moves rather than removes, and a drift view that names the change.

Default run: writes and deletes ONE scratch agent (``zz-builder-probe``) in
agents/instances/ and reads the drift. It does NOT roll out. With
``--deploy`` it also does increment 4's two hard scenarios against the gateway:

  T6   rollout twice -> the second run is a no-op (in_sync, nothing applied)
  T10  delete in the builder -> after rollout the gateway no longer lists it
  T11  a list the gateway's schema refuses stops the rollout at the dry run,
       before any `agents delete` (review A3)

Usage:
    python3 tests/agents/test_builder_api.py [--deploy]

Environment: SCRIPT_RUNNER_URL (default http://127.0.0.1:8096).
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

RUNNER = os.environ.get("SCRIPT_RUNNER_URL", "http://127.0.0.1:8096")
PROBE = "zz-builder-probe"
BASE_ID = "zz-builder-base"
BOGUS_ID = "zz-builder-bogus"

results: list[tuple[str, str, str]] = []


def record(verdict: str, subject: str, detail: str = "") -> None:
    results.append((verdict, subject, detail))
    mark = {"PASS": "  ok  ", "FAIL": " FAIL ", "WARN": " warn "}[verdict]
    print(f"[{mark}] {subject}{(': ' + detail) if detail else ''}")


def call(method: str, path: str, body: dict | None = None, timeout: int = 60) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{RUNNER}{path}", data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {}


def main() -> int:
    deploy = "--deploy" in sys.argv
    deadline = time.time() + 45
    while time.time() < deadline:
        try:
            if urllib.request.urlopen(f"{RUNNER}/health", timeout=3).status == 200:
                break
        except Exception:
            time.sleep(1)
    else:
        print(f"script-runner not healthy at {RUNNER}", file=sys.stderr)
        return 2

    # --- the parts list --------------------------------------------------
    st, j = call("GET", "/agents/models", timeout=90)
    models = j.get("models", [])
    local_model = next((m["key"] for m in models if m.get("local")), "llama-local/current")
    if st != 200 or not models:
        record("FAIL", "models", f"HTTP {st}: {str(j)[:120]}")
    else:
        local = [m["key"] for m in models if m["local"]]
        record("PASS" if local else "FAIL", "models", f"{len(models)} from the gateway, local: {local}")
        wrong = [m["key"] for m in models if m["local"] != m["key"].startswith("llama-local/")]
        record("PASS" if not wrong else "FAIL", "locality by prefix", "decided here, not by the gateway's field" if not wrong else str(wrong))

    st, j = call("GET", "/agents/skills")
    skills = {s["name"] for s in j.get("skills", [])}
    record("PASS" if st == 200 and "recherche" in skills else "FAIL", "skills", ", ".join(sorted(skills)))
    nodesc = [s["name"] for s in j.get("skills", []) if not s.get("description")]
    record("PASS" if not nodesc else "WARN", "every skill has a description", str(nodesc) if nodesc else "the part that reaches the prompt")

    st, j = call("GET", "/agents/tools")
    tools = j.get("tools", [])
    mcp = [t for t in tools if t.get("source") == "mcp"]
    gw = [t for t in tools if t.get("source") == "gateway"]
    record("PASS" if st == 200 and mcp and gw else "FAIL", "tools", f"{len(mcp)} MCP + {len(gw)} gateway")
    record("PASS" if any(t["id"] == "mora02__flow_run" for t in mcp) else "FAIL", "MCP ids carry the server prefix")
    lob = [t for t in gw if t["id"] == "lobster"]
    record("PASS" if lob and lob[0]["risk"] == "act" else "FAIL", "lobster is listed as acting", "the gate-dissolving tool is named, not hidden")

    st, j = call("GET", "/agents/skills/briefing")
    paths = [f.get("path") for f in j.get("files", [])]
    record("PASS" if st == 200 and "recherche/FRAGEN.md" in paths and all("content" in f for f in j.get("files", [])) else "FAIL",
           "skill files readable", ", ".join(paths))
    st, _ = call("GET", "/agents/skills/nope")
    record("PASS" if st == 404 else "FAIL", "unknown skill is 404", f"HTTP {st}")

    # --- the roster, builder view --------------------------------------------
    st, j = call("GET", "/agents/roster?include_inactive=true")
    ids = [a["id"] for a in j.get("agents", [])]
    record("PASS" if st == 200 and "main" not in ids else "FAIL", "main is never in the roster (reception desk, not an agent)", ", ".join(ids))

    st, j = call("GET", "/agents/roots")
    record("PASS" if st == 200 and j.get("local") and j.get("can_create") else "FAIL", "installation root mounted", str(j))

    st, _ = call("GET", "/agents/no-such-agent/detail")
    record("PASS" if st == 404 else "FAIL", "unknown agent is 404", f"HTTP {st}")
    st, j = call("PUT", "/agents/main", {"manifest": {"label": "x", "model": local_model, "tools": {"allow": ["read"]}}, "soul": "x"})
    record("PASS" if st == 422 and "reception" in str(j.get("detail", "")) else "FAIL", "main refused as an agent id (422)", str(j.get("detail", ""))[:80])

    # --- save: refusals first, then the real thing ----------------------------
    # Two scratch agents: BASE with its own limits and SOUL, PROBE borrowing
    # both. Nothing here depends on which agents this machine happens to have.
    own_limits = {"page_chars": 4000, "max_urls": 8, "max_queries": 8, "snippet_chars": 300,
                  "results_per_query": 8, "max_pages_total": 24, "max_searches_total": 8}
    st, j = call("PUT", f"/agents/{BASE_ID}", {"manifest": {"label": "Builder-Basis", "icon": "z", "description": "scratch base agent",
                                                        "active": False, "model": local_model, "timeout": 60,
                                                        "skills": ["recherche"], "tools": {"allow": ["read"]},
                                                        "limits": own_limits}, "soul": "# Basis\n"})
    record("PASS" if st == 200 else "FAIL", "scratch base agent created", str(j)[:80])
    base = {"label": "Builder-Probe", "icon": "z", "description": "scratch agent written by the test suite",
            "active": False, "model": local_model, "timeout": 60,
            "skills": ["recherche"], "tools": {"allow": ["read"]},
            "limits": {"same_as": BASE_ID}}
    st, j = call("PUT", f"/agents/{PROBE}", {"manifest": {**base, "tools": {"allow": []}}, "soul": "# x\n"})
    record("PASS" if st == 422 and "empty" in str(j.get("detail", "")).lower() else "FAIL", "empty tool list refused (422)", str(j.get("detail", ""))[:80])
    st, j = call("PUT", f"/agents/{PROBE}", {"manifest": {**base, "skills": ["nope"]}, "soul": "# x\n"})
    record("PASS" if st == 422 else "FAIL", "unknown skill refused (422)", str(j.get("detail", ""))[:80])
    st, j = call("PUT", "/agents/Bad%20Id", {"manifest": base, "soul": "# x\n"})
    record("PASS" if st == 422 else "FAIL", "bad id refused (422)", f"HTTP {st}")

    st, j = call("PUT", f"/agents/{PROBE}", {"manifest": base, "soul": "# Builder probe\n"})
    record("PASS" if st == 200 and j.get("created") and "/agents-local/" in j.get("path", "") else "FAIL",
           "PUT creates the agent under data/agents", str(j)[:100])
    st, j = call("PUT", f"/agents/{PROBE}", {"manifest": base, "soul": "# Builder probe\n"})
    record("PASS" if st == 200 and not j.get("created") else "FAIL", "second PUT is an update")
    st, j = call("PUT", f"/agents/{PROBE}", {"manifest": base, "soul": "# Builder probe\n", "files": {"USER.md": "kurz"}})
    st, j = call("GET", f"/agents/{PROBE}/detail")
    record("PASS" if (j.get("files") or {}).get("USER.md", "").startswith("kurz") else "FAIL", "extra workspace file round trip", str(j.get("files")))
    st, j = call("PUT", f"/agents/{PROBE}", {"manifest": base, "soul": "# Builder probe\n", "files": {"USER.md": ""}})
    st, j = call("GET", f"/agents/{PROBE}/detail")
    record("PASS" if not (j.get("files") or {}) else "FAIL", "empty string removes it", str(j.get("files")))
    record("PASS" if j.get("limits_effective") and j["limits_effective"].get("page_chars") else "FAIL",
           "borrowed limits resolve in detail", f"page_chars={ (j.get('limits_effective') or {}).get('page_chars') }")
    st, j = call("GET", "/agents/roster?include_inactive=true")
    record("PASS" if PROBE in [a["id"] for a in j.get("agents", [])] else "FAIL", "new agent appears in the roster by existing")
    st, j = call("PUT", f"/agents/{PROBE}", {"manifest": base, "soul_shared_with": BASE_ID})
    st, j = call("GET", f"/agents/{PROBE}/detail")
    record("PASS" if j.get("soul_shared_with") == BASE_ID and j.get("soul", "").startswith("# Basis") else "FAIL",
           "SOUL borrowed by reference", f"{len(j.get('soul', ''))} chars")
    st, j = call("PUT", f"/agents/{PROBE}", {"manifest": base, "soul": "# Builder probe\n"})

    # --- drift names the new agent -----------------------------------------
    st, j = call("GET", "/agents/drift", timeout=120)
    if st != 200:
        record("FAIL", "drift", f"HTTP {st}: {str(j)[:120]}")
    else:
        named = [d for d in j.get("drift", []) if f"agent/{PROBE}" in d]
        if named:
            record("PASS", "drift names the unrolled agent", named[0][:80])
        else:
            # A --deploy run that failed before T10 leaves the scratch agents
            # IN the gateway; re-created identically, they are then in sync and
            # there is no drift to name. That is residue, not a defect -- said
            # as a warning rather than a red line nobody can act on.
            st2, live = call("GET", "/agents", timeout=90)
            residue = PROBE in [a["id"] for a in live.get("agents", [])]
            record("WARN" if residue else "FAIL", "drift names the unrolled agent",
                   "the gateway still carries it from an earlier --deploy run that "
                   "did not reach T10; the case cannot be exercised until it is gone"
                   if residue else "-")

    if deploy:
        # T6 -- rollout twice, second is a no-op
        st, j = call("POST", "/agents/deploy", timeout=300)
        record("PASS" if st == 200 and j.get("ok") else "FAIL", "T6a rollout applies and verifies",
               j.get("detail") or f"applied={j.get('applied')} left={j.get('left')}")
        st, j2 = call("POST", "/agents/deploy", timeout=300)
        record("PASS" if st == 200 and j2.get("in_sync") and not j2.get("applied") else "FAIL",
               "T6b second rollout is a no-op", f"in_sync={j2.get('in_sync')} applied={j2.get('applied')}")
        st, j = call("GET", "/agents", timeout=90)
        record("PASS" if PROBE in [a["id"] for a in j.get("agents", [])] else "FAIL", "gateway lists the new agent")

        # T11 -- nothing is deleted before the gateway has validated the list
        # (review A3, 2026-09-03). A manifest the store accepts but the gateway's
        # schema does not (a number in tools.allow) must stop the rollout at
        # the dry run, and an agent trashed in the same rollout must survive
        # in the gateway: before the fix, `agents delete --force` ran first.
        # Its OWN limits, not BASE_ID's: this agent outlives the one the next
        # line trashes, and a borrow left dangling would make the roster refuse
        # the rollout for that instead -- which is what happened the first time
        # this ran (2026-09-04), and it proved nothing about the dry run.
        bogus = {**base, "tools": {"allow": ["read", 42]},
                 "limits": {"page_chars": 4000, "max_urls": 3, "max_queries": 5,
                            "snippet_chars": 160, "results_per_query": 5,
                            "max_pages_total": 12, "max_searches_total": 6}}
        st, j = call("PUT", f"/agents/{BOGUS_ID}", {"manifest": bogus, "soul": "# bogus\n"})
        # The probe borrows ITS limits from BASE_ID too, and BASE_ID is trashed
        # on the next line. A dangling borrow makes the roster refuse the
        # rollout before the gateway ever sees the bogus tool list, which is a
        # different refusal and proves nothing (measured 2026-09-04). Give the
        # probe its own numbers for the rest of this suite.
        call("PUT", f"/agents/{PROBE}", {"manifest": {**base, "limits": dict(own_limits)},
                                         "soul": "# Builder probe\n"})
        record("PASS" if st == 200 else "FAIL", "T11a store accepts what only the gateway can judge", f"HTTP {st}")
        st, j = call("DELETE", f"/agents/{BASE_ID}")
        record("PASS" if st == 200 else "FAIL", "T11b scratch base agent trashed beside it")
        st, j = call("POST", "/agents/deploy", timeout=300)
        refused = st != 200 or not j.get("ok")
        detail = (j.get("detail") or j.get("error") or str(j))[:160]
        if refused and "dry run" in detail:
            record("PASS", "T11c rollout refused at the dry run", detail)
        elif refused:
            record("FAIL", "T11c rollout refused, but not by the dry run", detail)
        else:
            record("WARN", "T11c gateway accepted a number in tools.allow; the guard could not be exercised", detail)
        st, j = call("GET", "/agents", timeout=90)
        live = [a["id"] for a in j.get("agents", [])]
        record("PASS" if (BASE_ID in live) == refused else "FAIL",
               "T11d trashed agent survives a refused rollout", f"{BASE_ID} live={BASE_ID in live} refused={refused}")
        st, j = call("DELETE", f"/agents/{BOGUS_ID}")
        record("PASS" if st == 200 else "FAIL", "T11e bogus agent trashed again; T10 takes it out")

    # --- delete moves ----------------------------------------------------------
    st, j = call("DELETE", f"/agents/{PROBE}")
    record("PASS" if st == 200 and ".trash/" in j.get("moved_to", "") else "FAIL", "DELETE moves to .trash", j.get("moved_to", str(j))[-40:])
    st, j = call("GET", "/agents/roster?include_inactive=true")
    record("PASS" if PROBE not in [a["id"] for a in j.get("agents", [])] else "FAIL", "trashed agent gone from the roster")
    st, j = call("DELETE", f"/agents/{PROBE}")
    record("PASS" if st == 404 else "FAIL", "deleting twice is 404", f"HTTP {st}")
    st, j = call("DELETE", f"/agents/{BASE_ID}")
    record("PASS" if st == 200 or (deploy and st == 404) else "FAIL", "scratch base agent removed", str(j)[-40:])

    if deploy:
        # T10 -- after rollout the gateway no longer lists it
        st, j = call("GET", "/agents/drift", timeout=120)
        record("PASS" if any("deleted in the roster" in d and PROBE in d for d in j.get("drift", [])) else "FAIL",
               "T10a drift reads the trash as intent")
        st, j = call("POST", "/agents/deploy", timeout=300)
        record("PASS" if st == 200 and j.get("ok") else "FAIL", "T10b rollout removes it",
               (j.get("detail") or str(j.get("log", [])))[-160:])
        st, j = call("GET", "/agents", timeout=90)
        live = [a["id"] for a in j.get("agents", [])]
        record("PASS" if not {PROBE, BASE_ID, BOGUS_ID} & set(live) else "FAIL", "T10c gateway no longer lists them",
               ", ".join(sorted({PROBE, BASE_ID, BOGUS_ID} & set(live))) or "all gone")
    else:
        record("WARN", "T6/T10 skipped", "pass --deploy to roll out against the gateway")

    # the trash folder keeps the probe; say so rather than clean up silently --
    # a test that deletes files outside its own scratch space is a test nobody
    # wants to run twice.
    print(f"\nnote: data/agents/instances/.trash/ now holds '{PROBE}-…', '{BASE_ID}-…' and (with --deploy) '{BOGUS_ID}-…' folders; remove them by hand when convenient")

    fails = [r for r in results if r[0] == "FAIL"]
    warns = [r for r in results if r[0] == "WARN"]
    print(f"{len(results) - len(fails) - len(warns)} passed, {len(warns)} warned, {len(fails)} failed")
    for _, s, d in fails:
        print(f"  FAILED  {s}: {d}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
