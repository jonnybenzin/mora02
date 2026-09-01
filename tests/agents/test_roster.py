#!/usr/bin/env python3
"""Does an agent come into being by existing, and does main stay out of the chat?

Increment 3's whole claim is that a new agent needs no code: one folder under
agents/instances/ is one agent, its folder name is its id, and both the rollout
and the Pilot find it by looking. This suite guards the half a browser can see —
the roster endpoint — including the two ways it could quietly go wrong:

  * a missing mount answers "no agents" instead of "not mounted", and the Pilot
    shows an empty list that looks like a configuration nobody made
  * main appears in the chat list, which offers a turn to the letterbox that
    sits on the Signal channel — the one agent whose narrow tool list exists
    precisely because strangers can reach it

Free and fast: it reads one endpoint and spends nothing.

Usage:
    python3 tests/agents/test_roster.py

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

results: list[tuple[str, str, str]] = []


def record(verdict: str, subject: str, detail: str) -> None:
    results.append((verdict, subject, detail))
    mark = {"PASS": "  ok  ", "FAIL": " FAIL ", "WARN": " warn "}[verdict]
    print(f"[{mark}] {subject}: {detail}")


def wait_ready(seconds: int = 45) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{RUNNER}/health", timeout=3) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(1)
    return False


def main() -> int:
    if not wait_ready():
        print(f"script-runner did not become healthy at {RUNNER}", file=sys.stderr)
        return 2

    try:
        with urllib.request.urlopen(f"{RUNNER}/agents/roster", timeout=30) as r:
            body = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:200]
        if e.code == 503:
            # The endpoint doing its job, and the suite still failing: the point
            # of the 503 is that this is fixable, so it must be loud here too.
            record("FAIL", "mount", f"the agents directory is not mounted — {detail}")
        else:
            record("FAIL", "roster", f"HTTP {e.code}: {detail}")
        return report()

    agents = body.get("agents")
    if not isinstance(agents, list) or not agents:
        record("FAIL", "roster", f"no agents returned: {str(body)[:160]}")
        return report()
    ids = [a.get("id") for a in agents]
    record("PASS", "roster", f"{len(agents)} agent(s): {', '.join(ids)}")

    # --- main must not be offered as somebody to talk to --------------------
    if "main" in ids:
        record("FAIL", "main hidden",
               "main is in the chat roster — it is the default agent an inbound "
               "Signal message lands on, not a persona")
    else:
        record("PASS", "main hidden", "the letterbox is not offered as a chat partner")

    # --- every entry must be usable by a UI ---------------------------------
    for a in agents:
        missing = [k for k in ("id", "label") if not a.get(k)]
        if missing:
            record("FAIL", f"entry {a.get('id')}", f"missing {missing}")
        elif not a.get("description"):
            # Not fatal, but a nameless row in a picker is a row nobody clicks.
            record("WARN", f"entry {a.get('id')}", "no description")
        else:
            record("PASS", f"entry {a.get('id')}",
                   f"{a.get('icon','')} {a['label']} — {a['description'][:44]}")

    # --- sorted, so a picker is stable across reloads -----------------------
    order = [(a.get("sort_order", 100), a.get("id")) for a in agents]
    if order == sorted(order):
        record("PASS", "order", "stable, by sort_order then id")
    else:
        record("FAIL", "order", f"not sorted: {order}")

    # --- the gateway's own view, for contrast -------------------------------
    # Two lists that can disagree: the roster is intent, /agents is what the
    # gateway actually carries. A roster entry the gateway does not know means
    # the rollout has not run — worth saying, not worth failing on, since this
    # suite is also how someone checks BEFORE rolling out.
    try:
        with urllib.request.urlopen(f"{RUNNER}/agents", timeout=60) as r:
            live = [a.get("id") for a in json.loads(r.read().decode()).get("agents", [])]
        unknown = [i for i in ids if i not in live]
        if unknown:
            record("WARN", "rollout",
                   f"in the roster but not in the gateway: {unknown} — run agents-deploy.py")
        else:
            record("PASS", "rollout", "every roster agent exists in the gateway")
    except Exception as e:
        record("WARN", "rollout", f"could not read the gateway's list: {e}")

    return report()


def report() -> int:
    print()
    fails = [r for r in results if r[0] == "FAIL"]
    warns = [r for r in results if r[0] == "WARN"]
    print(f"{len(results) - len(fails) - len(warns)} passed, "
          f"{len(warns)} warned, {len(fails)} failed")
    for _, subject, detail in fails:
        print(f"  FAILED  {subject}: {detail}")
    return 1 if fails else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except urllib.error.URLError as e:
        print(f"cannot reach script-runner at {RUNNER}: {e}", file=sys.stderr)
        sys.exit(2)
