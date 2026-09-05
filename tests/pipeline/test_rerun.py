#!/usr/bin/env python3
"""Phase 5 of the vocabulary test plan: is a partial re-run trustworthy?

A re-run replays what did not change and recomputes what did. That is only worth
having if it is exact: replaying one step too many means shipping a stale result,
and replaying a human decision means an approval nobody gave. Both failures look
like success, so each case here checks not the outcome but the bookkeeping -
which steps came back, which ran again, which approvals were asked for.

The suite builds its own source run first (seed, a value step, a gate, a second
value step), so it never depends on what happens to be lying in the log
directory.

Usage:
    python3 tests/pipeline/test_rerun.py

Environment: SCRIPT_RUNNER_URL (default http://127.0.0.1:8096),
MORA02_PIPELINE_LOG_DIR (default /opt/mora02/pipelines/logs).
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

RUNNER = os.environ.get("SCRIPT_RUNNER_URL", "http://127.0.0.1:8096")
LOG_DIR = Path(os.environ.get("MORA02_PIPELINE_LOG_DIR", "/opt/mora02/pipelines/logs"))
SEED_URL = "http://127.0.0.1:8096/health"

results: list[tuple[str, str, str]] = []


def record(verdict: str, subject: str, detail: str) -> None:
    results.append((verdict, subject, detail))


def post(path: str, payload: dict) -> dict:
    req = urllib.request.Request(f"{RUNNER}{path}", data=json.dumps(payload).encode("utf-8"),
                                 method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            return {"http_status": e.code, **json.loads(body)}
        except json.JSONDecodeError:
            return {"http_status": e.code, "detail": body}
    except Exception as e:
        return {"http_status": 0, "detail": f"{type(e).__name__}: {e}"}


def events(run_id: str) -> list[dict]:
    path = LOG_DIR / f"{run_id}.jsonl"
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out


def steps_of(run_id: str) -> dict:
    return {e["step_id"]: e for e in events(run_id)
            if e.get("kind") == "step" and e.get("step_id")}


BASE_STEPS = [
    {"web.fetch": {"id": "seed", "in": "none", "url": SEED_URL}},
    {"llm.classify": {"id": "first", "in": "seed", "labels": "ALPHA"}},
    {"gate": "Freigeben?"},
    {"llm.classify": {"id": "second", "in": "first", "labels": "BRAVO"}},
]


def make_source_run(approve: bool = True) -> tuple[str | None, dict]:
    """One completed run to re-run from. Returns (run_id, spec)."""
    spec = {"name": f"rerun-source-{int(time.time())}", "steps": BASE_STEPS}
    res = post("/pipeline/run-spec", {"spec": spec})
    run_id = res.get("run_id")
    if res.get("is_paused") and res.get("resume_token"):
        post("/pipeline/resume", {"token": res["resume_token"], "run_id": run_id,
                                  "response": {"approved": approve}})
    return run_id, spec


def case_plan(run_id: str, spec: dict) -> None:
    """The plan is the promise made before any GPU minute is spent."""
    plan = post("/pipeline/rerun-plan",
                {"source_run_id": run_id, "changed": ["second"], "spec": spec})
    if "http_status" in plan:
        record("FAIL", "rerun-plan · a late change", f"{plan.get('detail') or plan}")
        return
    redo, reuse = set(plan.get("redo", [])), set(plan.get("reuse", []))
    if "second" in redo and {"seed", "first"} <= reuse:
        record("PASS", "rerun-plan · a late change",
               f"redo={sorted(redo)} reuse={sorted(reuse)}")
    else:
        record("FAIL", "rerun-plan · a late change",
               f"expected only 'second' to redo; redo={sorted(redo)} reuse={sorted(reuse)}")

    # Changing the FIRST step must carry everything that reads it along.
    plan2 = post("/pipeline/rerun-plan",
                 {"source_run_id": run_id, "changed": ["first"], "spec": spec})
    redo2 = set(plan2.get("redo", []))
    if {"first", "second"} <= redo2 and "seed" not in redo2:
        record("PASS", "rerun-plan · an early change carries the tail",
               f"redo={sorted(redo2)}")
    else:
        record("FAIL", "rerun-plan · an early change carries the tail",
               f"expected first+second stale, seed reused; redo={sorted(redo2)}")

    # "gates_needed" does not mean "approvals you will be asked for". Its own
    # definition is the opposite: gates a redone step waits on that are NOT
    # themselves redone, so their earlier decision has to be inherited (and is
    # checked against a refusal before it is). The question a human actually
    # asks - will this stop and ask me? - is answered by redo containing the
    # gate. Both readings are asserted here so neither can drift unnoticed.
    plan3 = post("/pipeline/rerun-plan",
                 {"source_run_id": run_id, "changed": ["second"], "spec": spec})
    if plan3.get("gates_needed") == ["gate"]:
        record("PASS", "rerun-plan · an inherited decision is named",
               "the gate a reused decision comes from is listed")
    else:
        record("FAIL", "rerun-plan · an inherited decision is named",
               f"changing a step behind the gate should inherit its decision; "
               f"gates_needed={plan3.get('gates_needed')}")

    rr = post("/pipeline/rerun", {"source_run_id": run_id, "changed": ["first"],
                                  "spec": spec})
    will_pause = bool(rr.get("is_paused"))
    if rr.get("resume_token"):
        post("/pipeline/resume", {"token": rr["resume_token"], "run_id": rr.get("run_id"),
                                  "response": {"approved": True}})
    if ("gate" in redo2) == will_pause:
        record("PASS", "rerun-plan · redo says whether you will be asked",
               f"gate in redo={('gate' in redo2)}, re-run pauses={will_pause}")
    else:
        record("FAIL", "rerun-plan · redo says whether you will be asked",
               f"gate in redo={('gate' in redo2)} but the re-run pauses={will_pause}")


def case_override(run_id: str, spec: dict) -> None:
    """An override must actually reach the step it names."""
    res = post("/pipeline/rerun", {
        "source_run_id": run_id, "changed": ["second"], "spec": spec,
        "overrides": {"second": {"labels": "GAMMA,ALPHA"}},
    })
    if res.get("is_paused") and res.get("resume_token"):
        res = post("/pipeline/resume", {"token": res["resume_token"],
                                        "run_id": res.get("run_id"),
                                        "response": {"approved": True}})
    new_run = res.get("run_id")
    ev = steps_of(new_run).get("second") if new_run else None
    # Judge the PARAMETER the step was called with, not the model's answer: an op
    # is responsible for receiving the override, not for what a model does with
    # it. Conflating the two reads a model quirk as a broken feature.
    got = (ev or {}).get("params", {}).get("labels")
    if got == "GAMMA,ALPHA":
        record("PASS", "rerun · override takes effect",
               "the step was called with the overridden value")
    elif ev:
        record("FAIL", "rerun · override takes effect",
               f"step was called with labels={got!r} - the override never arrived")
    else:
        record("FAIL", "rerun · override takes effect",
               f"the changed step did not run at all: {str(res)[:100]}")

    # Separate question, found while reading the above: llm.classify promises to
    # pick exactly one of its labels. Handed a text that says something else, it
    # answered with the text instead - the op does not check its own contract.
    out = (ev or {}).get("out")
    if got and out and out not in got.split(","):
        record("FAIL", "llm.classify answers with one of its labels",
               f"labels={got}, answer={out!r} - not one of the labels")
    elif got:
        record("PASS", "llm.classify answers with one of its labels",
               f"labels={got}, answer={out!r}")


def case_replay_is_marked(run_id: str, spec: dict) -> None:
    """A replayed step must be visible AS replayed, not as fresh work."""
    res = post("/pipeline/rerun", {"source_run_id": run_id, "changed": ["second"],
                                   "spec": spec})
    if res.get("is_paused") and res.get("resume_token"):
        res = post("/pipeline/resume", {"token": res["resume_token"],
                                        "run_id": res.get("run_id"),
                                        "response": {"approved": True}})
    new_run = res.get("run_id")
    st = steps_of(new_run) if new_run else {}
    seed_ev = st.get("seed")
    if seed_ev and seed_ev.get("status") == "replayed":
        record("PASS", "rerun · replay is labelled", "the reused step says 'replayed'")
    elif seed_ev:
        record("FAIL", "rerun · replay is labelled",
               f"the reused step is logged as {seed_ev.get('status')!r} - a replay "
               "that looks like fresh work hides what the run actually did")
    else:
        record("FAIL", "rerun · replay is labelled", "no event for the reused step")


def case_no_recorded_spec() -> None:
    """Runs from before spec recording must fail clearly, not mysteriously."""
    old = None
    for path in sorted(LOG_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime):
        evs = [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]
        start = next((e for e in evs if e.get("kind") == "run_start"), None)
        if evs and (start is None or start.get("spec") is None):
            old = path.stem
            break
    if old is None:
        record("n/a", "rerun · run without a recorded spec",
               "no such run left in the log directory")
        return
    res = post("/pipeline/rerun", {"source_run_id": old, "changed": []})
    status = res.get("http_status")
    if status in (404, 409) and res.get("detail"):
        record("PASS", "rerun · run without a recorded spec",
               f"{status}: {str(res['detail'])[:80]}")
    else:
        record("FAIL", "rerun · run without a recorded spec",
               f"expected a clean 409/404, got {status}: {str(res)[:90]}")


def case_rejected_gate() -> None:
    """A re-run must not inherit an approval that was actually a refusal."""
    run_id, spec = make_source_run(approve=False)
    if not run_id:
        record("FAIL", "rerun · a refusal is not an approval", "could not build a refused run")
        return
    res = post("/pipeline/rerun", {"source_run_id": run_id, "changed": ["second"],
                                   "spec": spec})
    if res.get("is_paused"):
        record("PASS", "rerun · a refusal is not an approval",
               "the re-run stops at the gate and asks again")
        return
    new_run = res.get("run_id")
    ran = steps_of(new_run).get("second") if new_run else None
    if ran:
        record("FAIL", "rerun · a refusal is not an approval",
               "the step behind a REFUSED gate ran in the re-run without asking")
    else:
        record("PASS", "rerun · a refusal is not an approval",
               "nothing behind the refused gate ran")


def main() -> int:
    run_id, spec = make_source_run(approve=True)
    if not run_id:
        print("could not create a source run - is the stack up?")
        return 1
    case_plan(run_id, spec)
    case_override(run_id, spec)
    case_replay_is_marked(run_id, spec)
    case_no_recorded_spec()
    case_rejected_gate()

    width = max(len(s) for _, s, _ in results)
    failed = sum(1 for v, _, _ in results if v == "FAIL")
    na = sum(1 for v, _, _ in results if v == "n/a")
    for verdict, subject, detail in results:
        print(f"{verdict:4}  {subject.ljust(width)}  {detail}")
    print(f"\n{len(results) - failed - na} passed, {failed} failed, {na} not applicable")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
