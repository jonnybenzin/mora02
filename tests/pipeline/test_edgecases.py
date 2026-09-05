#!/usr/bin/env python3
"""Phase 8 of the test plan: the combinations nobody would build on purpose.

Every other suite asks whether the system does what it promises. This one asks
what it does when nobody is being reasonable - a picture handed to a text op, a
chain with a gate at both ends, a prompt of five thousand characters, two flows
racing for the same run bucket. Systems rarely break where they are used well.

The point is not that every case must succeed. Some of these SHOULD be refused.
The point is that the outcome is decided and visible rather than accidental: a
refusal names its reason, and a success is a success rather than a value that
happens to look like one.

Usage:
    python3 tests/pipeline/test_edgecases.py

Environment: SCRIPT_RUNNER_URL (default http://127.0.0.1:8096),
MORA02_PIPELINE_LOG_DIR (default /opt/mora02/pipelines/logs).
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

RUNNER = os.environ.get("SCRIPT_RUNNER_URL", "http://127.0.0.1:8096")
LOG_DIR = Path(os.environ.get("MORA02_PIPELINE_LOG_DIR", "/opt/mora02/pipelines/logs"))
SEED_URL = "http://127.0.0.1:8096/health"

TEXT_SEED = {"web.fetch": {"id": "seed", "in": "none", "url": SEED_URL}}
PIC_SEED = {"source.file": {"id": "pic", "in": "none", "store": "comfyui", "pick": "latest"}}

results: list[tuple[str, str, str]] = []


def record(verdict: str, subject: str, detail: str) -> None:
    results.append((verdict, subject, detail))
    print(f"{verdict:4}  {subject}  {detail}", flush=True)


def post(path: str, payload: dict, timeout: int = 600) -> dict:
    req = urllib.request.Request(f"{RUNNER}{path}", data=json.dumps(payload).encode("utf-8"),
                                 method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            return {"http_status": e.code, **json.loads(body)}
        except json.JSONDecodeError:
            return {"http_status": e.code, "detail": body}
    except Exception as e:
        return {"http_status": 0, "detail": f"{type(e).__name__}: {e}"}


def run_spec(name: str, steps: list, timeout: int = 600) -> dict:
    return post("/pipeline/run-spec",
                {"spec": {"name": f"{name}-{int(time.time()*1000)%100000}", "steps": steps},
                 "trigger": "test"},
                timeout=timeout)


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


# --- A. a picture handed to a text op ---------------------------------------

def case_picture_into_text_op() -> None:
    """An image ref where a text op expects prose.

    The ref is a perfectly good string, so nothing crashes - the model is handed
    "asset://comfyui/x.png" and dutifully summarises it. That is the quiet kind of
    wrong: a step reports ok and passes on a summary of a filename. The question
    is whether anything in the chain notices.
    """
    res = run_spec("edge-pic-into-text", [
        PIC_SEED, {"llm.summarize": {"id": "probe", "in": "pic", "max_tokens": 40}}])
    if res.get("http_status"):
        record("PASS", "picture into a text op",
               f"refused before running: {str(res.get('detail'))[:80]}")
        return
    ev = steps_of(res.get("run_id", "")).get("probe")
    if ev is None:
        record("FAIL", "picture into a text op", "no step event")
    elif ev.get("status") != "ok":
        record("PASS", "picture into a text op",
               f"refused at runtime: {str(ev.get('error'))[:80]}")
    else:
        record("FAIL", "picture into a text op",
               f"summarised the reference itself and reported ok: {str(ev.get('out'))[:70]!r}")


# --- B. a gate at both ends --------------------------------------------------

def case_gates_at_both_ends() -> None:
    """Ten steps, a gate first and a gate last. Two pauses, in order, nothing skipped."""
    # Every step reads the neutral seed rather than its predecessor's label. Fed
    # its own predecessor's answer, the model echoes that instead of choosing the
    # label offered - and llm.classify now refuses an answer outside its labels,
    # so the chain would die of the test's own fixture rather than of anything
    # this case is about.
    steps: list = [{"gate": {"id": "g_first", "prompt": "Ganz am Anfang freigeben?"}},
                   TEXT_SEED]
    for n in range(1, 8):
        steps.append({"llm.classify": {"id": f"s{n}", "in": "seed", "labels": f"L{n}"}})
    steps.append({"gate": {"id": "g_last", "prompt": "Ganz am Ende abnehmen?"}})

    res = run_spec("edge-gates-both-ends", steps)
    if not res.get("is_paused"):
        record("FAIL", "gate at both ends", f"did not pause at the first gate: {str(res)[:90]}")
        return
    run_id = res.get("run_id")
    mid = post("/pipeline/resume", {"token": res["resume_token"], "run_id": run_id,
                                    "response": {"approved": True}})
    if not mid.get("is_paused"):
        record("FAIL", "gate at both ends",
               f"the closing gate never paused: {str(mid)[:90]}")
        return
    done = post("/pipeline/resume", {"token": mid["resume_token"], "run_id": run_id,
                                     "response": {"approved": True}})
    ran = [sid for sid in steps_of(run_id) if re.fullmatch(r"s\d+", sid)]
    if done.get("ok") and len(ran) == 7:
        record("PASS", "gate at both ends",
               f"two pauses, all {len(ran)} steps between them ran")
    else:
        record("FAIL", "gate at both ends",
               f"ok={done.get('ok')}, steps that ran: {sorted(ran)}")


# --- C. fan-in across a gate -------------------------------------------------

def case_fanin_across_gate() -> None:
    """Collect a step from BEFORE a gate together with steps from after it.

    The values live in the same run bucket but on opposite sides of a human
    decision. Nothing forbids it, and it is exactly the shape a real flow takes
    when an approved image is combined with things made after the approval.
    """
    res = run_spec("edge-fanin-across-gate", [
        PIC_SEED,
        {"gate": {"id": "g", "prompt": "Bild freigegeben?"}},
        {"source.file": {"id": "pic2", "in": "none", "store": "comfyui", "pick": "latest"}},
        {"gif.create": {"id": "probe", "in": ["pic", "pic2"]}},
    ])
    if not res.get("is_paused"):
        record("FAIL", "fan-in across a gate", f"no pause: {str(res)[:90]}")
        return
    run_id = res.get("run_id")
    done = post("/pipeline/resume", {"token": res["resume_token"], "run_id": run_id,
                                     "response": {"approved": True}})
    ev = steps_of(run_id).get("probe")
    if ev and ev.get("status") == "ok" and str(ev.get("out", "")).startswith("asset://"):
        record("PASS", "fan-in across a gate",
               f"combined both sides of the decision -> {str(ev['out'])[:50]}")
    elif ev:
        record("FAIL", "fan-in across a gate", f"{ev.get('status')}: {str(ev.get('error'))[:80]}")
    else:
        record("FAIL", "fan-in across a gate", f"the fan-in step never ran: {str(done)[:80]}")


# --- D. nothing and far too much --------------------------------------------

def case_empty_and_huge_prompt() -> None:
    res = run_spec("edge-empty-prompt", [
        TEXT_SEED, {"llm.complete": {"id": "probe", "in": "none", "prompt": ""}}])
    ev = steps_of(res.get("run_id", "")).get("probe")
    refused = bool(res.get("http_status")) or (ev and ev.get("status") != "ok")
    reason = str((ev or {}).get("error") or res.get("detail") or "")
    record("PASS" if refused and reason else "FAIL", "an empty prompt",
           f"refused: {reason[:80]}" if refused and reason
           else "accepted an empty prompt without a word")

    huge = "Beschreibe einen Leuchtturm. " * 180  # ~5000 characters
    res = run_spec("edge-huge-prompt", [
        TEXT_SEED, {"llm.complete": {"id": "probe", "in": "none",
                                     "prompt": huge, "max_tokens": 60}}], timeout=900)
    ev = steps_of(res.get("run_id", "")).get("probe")
    if ev and ev.get("status") == "ok":
        record("PASS", "a 5000-character prompt",
               f"{len(huge)} chars accepted -> {str(ev.get('out'))[:50]!r}")
    elif ev:
        record("PASS", "a 5000-character prompt",
               f"refused with a reason: {str(ev.get('error'))[:80]}")
    else:
        record("FAIL", "a 5000-character prompt",
               f"neither ran nor said why: {str(res)[:80]}")


# --- E. two flows at once ----------------------------------------------------

def case_two_flows_at_once() -> None:
    """Two runs in parallel, each with its own values.

    The run bucket is keyed by run id, so they must not see each other. If they
    did, the damage would be invisible: each flow would simply carry on with the
    other's value.
    """
    out: dict[str, dict] = {}

    def go(tag: str, label: str) -> None:
        out[tag] = run_spec(f"edge-parallel-{tag}", [
            TEXT_SEED, {"llm.classify": {"id": "probe", "in": "seed", "labels": label}}])

    threads = [threading.Thread(target=go, args=("a", "AAAA")),
               threading.Thread(target=go, args=("b", "BBBB"))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    vals = {}
    for tag in ("a", "b"):
        run_id = out.get(tag, {}).get("run_id")
        ev = steps_of(run_id).get("probe") if run_id else None
        vals[tag] = (ev or {}).get("out")
    if vals["a"] == "AAAA" and vals["b"] == "BBBB":
        record("PASS", "two flows at the same time", "each run kept its own values")
    else:
        record("FAIL", "two flows at the same time",
               f"values crossed over: {vals}")


def main() -> int:
    case_picture_into_text_op()
    case_gates_at_both_ends()
    case_fanin_across_gate()
    case_empty_and_huge_prompt()
    case_two_flows_at_once()

    width = max(len(s) for _, s, _ in results)
    failed = sum(1 for v, _, _ in results if v == "FAIL")
    print()
    for verdict, subject, detail in results:
        print(f"{verdict:4}  {subject.ljust(width)}  {detail}")
    print(f"\n{len(results) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
