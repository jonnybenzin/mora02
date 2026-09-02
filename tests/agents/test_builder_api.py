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

    # --- the roster, builder view --------------------------------------------
    st, j = call("GET", "/agents/roster?include_inactive=true")
    ids = [a["id"] for a in j.get("agents", [])]
    record("PASS" if "main" in ids else "FAIL", "roster with inactive shows main")
    st, j = call("GET", "/agents/roster")
    record("PASS" if "main" not in [a["id"] for a in j.get("agents", [])] else "FAIL", "roster without flag hides main")

    st, j = call("GET", "/agents/recherche-plus/detail")
    record("PASS" if st == 200 and j.get("soul_shared_with") == "recherche" else "FAIL",
           "detail", f"soul shared with {j.get('soul_shared_with')!r}, {len(j.get('limits_effective') or {})} limits")
    st, _ = call("GET", "/agents/no-such-agent/detail")
    record("PASS" if st == 404 else "FAIL", "unknown agent is 404", f"HTTP {st}")

    # --- save: refusals first, then the real thing ----------------------------
    base = {"label": "Builder-Probe", "icon": "z", "description": "scratch agent written by the test suite",
            "active": False, "model": "llama-local/qwen3-14b", "timeout": 60,
            "skills": ["recherche"], "tools": {"allow": ["read"]},
            "limits": {"same_as": "recherche"}}
    st, j = call("PUT", f"/agents/{PROBE}", {"manifest": {**base, "tools": {"allow": []}}, "soul": "# x\n"})
    record("PASS" if st == 422 and "empty" in str(j.get("detail", "")).lower() else "FAIL", "empty tool list refused (422)", str(j.get("detail", ""))[:80])
    st, j = call("PUT", f"/agents/{PROBE}", {"manifest": {**base, "skills": ["nope"]}, "soul": "# x\n"})
    record("PASS" if st == 422 else "FAIL", "unknown skill refused (422)", str(j.get("detail", ""))[:80])
    st, j = call("PUT", "/agents/Bad%20Id", {"manifest": base, "soul": "# x\n"})
    record("PASS" if st == 422 else "FAIL", "bad id refused (422)", f"HTTP {st}")

    st, j = call("PUT", f"/agents/{PROBE}", {"manifest": base, "soul": "# Builder probe\n"})
    record("PASS" if st == 200 and j.get("created") else "FAIL", "PUT creates the agent", str(j)[:100])
    st, j = call("PUT", f"/agents/{PROBE}", {"manifest": base, "soul": "# Builder probe\n"})
    record("PASS" if st == 200 and not j.get("created") else "FAIL", "second PUT is an update")
    st, j = call("GET", f"/agents/{PROBE}/detail")
    record("PASS" if j.get("limits_effective") and j["limits_effective"].get("page_chars") else "FAIL",
           "borrowed limits resolve in detail", f"page_chars={ (j.get('limits_effective') or {}).get('page_chars') }")
    st, j = call("GET", "/agents/roster?include_inactive=true")
    record("PASS" if PROBE in [a["id"] for a in j.get("agents", [])] else "FAIL", "new agent appears in the roster by existing")

    # --- drift names the new agent -----------------------------------------
    st, j = call("GET", "/agents/drift", timeout=120)
    if st != 200:
        record("FAIL", "drift", f"HTTP {st}: {str(j)[:120]}")
    else:
        named = [d for d in j.get("drift", []) if f"agent/{PROBE}" in d]
        record("PASS" if named else "FAIL", "drift names the unrolled agent", (named or ["-"])[0][:80])

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

    # --- delete moves ----------------------------------------------------------
    st, j = call("DELETE", f"/agents/{PROBE}")
    record("PASS" if st == 200 and ".trash/" in j.get("moved_to", "") else "FAIL", "DELETE moves to .trash", j.get("moved_to", str(j))[-40:])
    st, j = call("GET", "/agents/roster?include_inactive=true")
    record("PASS" if PROBE not in [a["id"] for a in j.get("agents", [])] else "FAIL", "trashed agent gone from the roster")
    st, j = call("DELETE", f"/agents/{PROBE}")
    record("PASS" if st == 404 else "FAIL", "deleting twice is 404", f"HTTP {st}")

    if deploy:
        # T10 -- after rollout the gateway no longer lists it
        st, j = call("GET", "/agents/drift", timeout=120)
        record("PASS" if any("deleted in the roster" in d and PROBE in d for d in j.get("drift", [])) else "FAIL",
               "T10a drift reads the trash as intent")
        st, j = call("POST", "/agents/deploy", timeout=300)
        record("PASS" if st == 200 and j.get("ok") else "FAIL", "T10b rollout removes it",
               (j.get("detail") or str(j.get("log", [])))[-160:])
        st, j = call("GET", "/agents", timeout=90)
        record("PASS" if PROBE not in [a["id"] for a in j.get("agents", [])] else "FAIL", "T10c gateway no longer lists it")
    else:
        record("WARN", "T6/T10 skipped", "pass --deploy to roll out against the gateway")

    # the trash folder keeps the probe; say so rather than clean up silently --
    # a test that deletes files outside its own scratch space is a test nobody
    # wants to run twice.
    print(f"\nnote: agents/instances/.trash/ now holds a '{PROBE}-…' folder; remove it by hand when convenient")

    fails = [r for r in results if r[0] == "FAIL"]
    warns = [r for r in results if r[0] == "WARN"]
    print(f"{len(results) - len(fails) - len(warns)} passed, {len(warns)} warned, {len(fails)} failed")
    for _, s, d in fails:
        print(f"  FAILED  {s}: {d}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
