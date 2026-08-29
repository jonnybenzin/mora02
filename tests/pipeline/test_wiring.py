#!/usr/bin/env python3
"""Phase 3 of the vocabulary test plan: does a value reach the step that asked for it?

A chain of two steps is easy - the value simply flows on. The interesting cases
are the ones a flow builder produces once it grows: a step that reaches back
past seven others, three branches folded into one consumer in a fixed order, a
picture reference travelling beside text values, and a step whose wiring nobody
declared at all.

Every value here is chosen, not observed: `llm.classify` with a SINGLE label can
only answer with that label, which turns a free local model call into a
deterministic emitter. A step's real input is read back from the run log, which
records what each step received.

Usage:
    python3 tests/pipeline/test_wiring.py

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
# A short, always-available page inside the docker network: the seed value that
# gives the first classify step something to chew on.
SEED_URL = "http://127.0.0.1:8096/health"

results: list[tuple[str, str, str]] = []


def record(verdict: str, subject: str, detail: str) -> None:
    results.append((verdict, subject, detail))


def _post(path: str, data: bytes, ctype: str) -> tuple[int, str]:
    req = urllib.request.Request(f"{RUNNER}{path}", data=data, method="POST",
                                 headers={"Content-Type": ctype})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}"


def run_spec(spec: dict) -> tuple[int, str]:
    return _post("/pipeline/run-spec", json.dumps({"spec": spec}).encode("utf-8"),
                 "application/json")


def step(op: str, body: str, query: str) -> tuple[int, str]:
    return _post(f"/pipeline/step/{op}?{query}", body.encode("utf-8"),
                 "text/plain; charset=utf-8")


def _post_get(path: str) -> str:
    with urllib.request.urlopen(f"{RUNNER}{path}", timeout=30) as r:
        return r.read().decode("utf-8", "replace")


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


def latest_run_for(pipeline_name: str) -> str | None:
    """The newest run log whose run_start names this pipeline."""
    best = None
    for path in sorted(LOG_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime,
                       reverse=True)[:40]:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("kind") == "run_start" and e.get("pipeline") == pipeline_name:
                return path.stem
            break
    return best


def step_event(run_id: str, step_id: str) -> dict | None:
    return next((e for e in events(run_id)
                 if e.get("kind") == "step" and e.get("step_id") == step_id), None)


def emitter(step_id: str, label: str, wire) -> dict:
    """A step that can only answer one way - a chosen value, from a real model."""
    cfg = {"id": step_id, "labels": label}
    if wire is not None:
        cfg["in"] = wire
    return {"llm.classify": cfg}


# --- A. a reference reaching back past seven steps --------------------------

def case_distance() -> None:
    name = f"wiring-distance-{int(time.time())}"
    steps = [{"web.fetch": {"id": "seed", "in": "none", "url": SEED_URL}},
             emitter("s1", "ALPHA", "seed")]
    prev = "s1"
    for n in range(2, 8):
        steps.append(emitter(f"s{n}", f"FILL{n}", prev))
        prev = f"s{n}"
    # The last step's LABEL comes from s1, seven steps back. classify can only
    # answer with a label, so the output IS the resolved reference.
    steps.append({"llm.classify": {"id": "far", "in": prev, "labels": {"from": "s1"}}})

    status, resp = run_spec({"name": name, "steps": steps})
    if status != 200:
        record("FAIL", "reference over 7 steps", f"run refused: {status} {resp[:120]}")
        return
    run_id = latest_run_for(name)
    ev = step_event(run_id, "far") if run_id else None
    if ev is None:
        record("FAIL", "reference over 7 steps", f"no step event for 'far' (run {run_id})")
    elif ev.get("out") == "ALPHA":
        record("PASS", "reference over 7 steps", "step 9 received step 2's value (ALPHA)")
    else:
        record("FAIL", "reference over 7 steps",
               f"expected ALPHA from s1, got {ev.get('out')!r}")


# --- B. three branches folded into one, in the order they were listed -------

def case_fanin_order() -> None:
    run_id = f"wiring-fanin-{int(time.time())}"
    for sid, label in (("a", "AAA"), ("b", "BBB"), ("c", "CCC")):
        step("llm.classify", "text zum einordnen",
             f"labels={label}&run_id={run_id}&step_id={sid}&fmt=out")
    # Collect them in a deliberately non-alphabetical order. image.edit refuses a
    # text input at once - no GPU, no cost - and the run log records what it was
    # handed, which is the only readout of the order that matters.
    step("image.edit", "", f"__collect=c,a,b&prompt=x&run_id={run_id}&step_id=fold")
    ev = step_event(run_id, "fold")
    got = [i.get("value", i.get("ref")) for i in (ev or {}).get("inputs", [])]
    if got == ["CCC", "AAA", "BBB"]:
        record("PASS", "fan-in keeps list order", f"collected c,a,b -> {got}")
    elif got:
        record("FAIL", "fan-in keeps list order",
               f"expected ['CCC','AAA','BBB'] (the listed order), got {got}")
    else:
        record("FAIL", "fan-in keeps list order", "no inputs recorded for the fan-in step")


# --- C. a picture reference travelling beside text values -------------------

def case_mixed_types() -> None:
    run_id = f"wiring-mixed-{int(time.time())}"
    status, ref = step("source.file", "",
                       f"store=comfyui&pick=latest&run_id={run_id}&step_id=pic&fmt=out")
    if status != 200 or not ref.startswith("asset://"):
        record("n/a", "image ref survives distance",
               f"no image in the comfyui store to test with ({status}: {ref[:60]})")
        return
    step("llm.classify", "text", f"labels=NOISE&run_id={run_id}&step_id=noise&fmt=out")
    # web.fetch reports the URL it could not reach, so its failure message is the
    # readout: if the reference resolved, the ref itself appears in the error.
    step("web.fetch", "", f"__ref_url=pic&run_id={run_id}&step_id=reader")
    ev = step_event(run_id, "reader")
    err = (ev or {}).get("error", "")
    # The readout is the protocol it choked on: httpx only ever sees "asset://"
    # if the reference was resolved into the url param in the first place.
    if "asset://" in err or ref.split("/")[-1] in err:
        record("PASS", "image ref survives distance",
               "the picture reference reached a later step past a text step")
    else:
        record("FAIL", "image ref survives distance",
               f"reference did not arrive: {err[:100]!r}")


# --- D. the step nobody wired ------------------------------------------------

def case_implicit_wiring() -> None:
    """A step nobody wired must still say what it is wired to.

    The default - a step without `in:` takes the previous step's output - is not
    wrong, it is invisible: the file does not say it and the builder cannot draw
    it, so two branches that look independent silently form one chain. The fix
    is not to forbid the default but to write it down at both doors a spec comes
    through, saving and running. This checks both, and reads the RECORDED spec
    rather than the file, because that is what a later partial re-run uses.
    """
    steps = [
        {"web.fetch": {"id": "seed", "in": "none", "url": SEED_URL}},
        emitter("branch1", "ALPHA", "seed"),
        {"llm.classify": {"id": "branch2", "labels": "BRAVO"}},  # no "in" at all
    ]

    # Door 1: saving. The library file must carry the wire.
    flow = f"wiring-materialised-{int(time.time())}"
    status, resp = _post(f"/pipeline/flow/{flow}?overwrite=true",
                         json.dumps({"steps": steps}).encode("utf-8"), "application/json")
    if status != 200:
        record("FAIL", "saving writes the wiring down", f"{status}: {resp[:110]}")
    else:
        back = json.loads(_post_get(f"/pipeline/flow/{flow}"))
        saved = next((st for st in back.get("steps", []) if "llm.classify" in st
                      and st["llm.classify"].get("id") == "branch2"), None)
        wired = (saved or {}).get("llm.classify", {}).get("in")
        if wired == "branch1":
            record("PASS", "saving writes the wiring down",
                   "the undeclared step was saved as in:'branch1'")
        else:
            record("FAIL", "saving writes the wiring down",
                   f"saved step still has in={wired!r}")
        # Take the probe flow back out of the library: a test that leaves files
        # in pipelines/specs/ pollutes the very thing it is checking.
        req = urllib.request.Request(f"{RUNNER}/pipeline/flow/{flow}", method="DELETE")
        try:
            urllib.request.urlopen(req, timeout=30).read()
        except Exception:
            record("FAIL", "saving writes the wiring down · cleanup",
                   f"could not remove the probe flow {flow!r} - delete it by hand")

    # Door 2: running the editor's stack without saving it.
    name = f"wiring-implicit-{int(time.time())}"
    status, resp = run_spec({"name": name, "steps": steps})
    if status != 200:
        record("FAIL", "running records the wiring", f"run refused: {status} {resp[:100]}")
        return
    run_id = latest_run_for(name)
    start = next((e for e in events(run_id) if e.get("kind") == "run_start"), None) if run_id else None
    recorded = (start or {}).get("spec") or {}
    step2 = next((st for st in recorded.get("steps", [])
                  if isinstance(st, dict) and "llm.classify" in st
                  and st["llm.classify"].get("id") == "branch2"), None)
    got = (step2 or {}).get("llm.classify", {}).get("in")
    if got == "branch1":
        record("PASS", "running records the wiring",
               "the run log records in:'branch1' - a re-run reads what really ran")
    else:
        record("FAIL", "running records the wiring",
               f"the recorded spec still hides the wire: in={got!r}")


def main() -> int:
    case_distance()
    case_fanin_order()
    case_mixed_types()
    case_implicit_wiring()

    width = max(len(s) for _, s, _ in results)
    failed = sum(1 for v, _, _ in results if v == "FAIL")
    na = sum(1 for v, _, _ in results if v == "n/a")
    for verdict, subject, detail in results:
        print(f"{verdict:4}  {subject.ljust(width)}  {detail}")
    print(f"\n{len(results) - failed - na} passed, {failed} failed, {na} not applicable")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
