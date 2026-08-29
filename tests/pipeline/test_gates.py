#!/usr/bin/env python3
"""Phase 4 of the vocabulary test plan: do human decisions land where they belong?

A gate is the one place where a pipeline waits for a person. Everything about it
is asymmetric: approving costs nothing, and a decision attributed to the wrong
gate approves something nobody looked at. With several gates in one flow the
riskiest assumption in the whole build is that the n-th decision answers the
n-th gate - so that is tested with two gates whose answers are told apart by
their content, not by their position.

Only `gate` is used here, never `review`: a review expands into notify + gate
and would send a real message. A test must not ring anyone's phone.

Usage:
    python3 tests/pipeline/test_gates.py

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

# A gate whose answer is a WORD, not a yes/no - so two decisions can be told
# apart by their content and attribution becomes observable.
WORD_SCHEMA = {"type": "object", "properties": {"word": {"type": "string"}},
               "required": ["word"]}

results: list[tuple[str, str, str]] = []


def record(verdict: str, subject: str, detail: str) -> None:
    results.append((verdict, subject, detail))


def _post(path: str, payload: dict) -> dict:
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


def run_spec(spec: dict) -> dict:
    return _post("/pipeline/run-spec", {"spec": spec})


def resume(token: str, run_id: str | None = None, **kw) -> dict:
    payload = {"token": token}
    if run_id:
        payload["run_id"] = run_id
    payload.update(kw)
    return _post("/pipeline/resume", payload)


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


def step_event(run_id: str, step_id: str) -> dict | None:
    return next((e for e in events(run_id)
                 if e.get("kind") == "step" and e.get("step_id") == step_id), None)


def seed() -> dict:
    return {"web.fetch": {"id": "seed", "in": "none", "url": SEED_URL}}


def name(tag: str) -> str:
    return f"gates-{tag}-{int(time.time())}"


# --- gate position -----------------------------------------------------------

def case_positions() -> None:
    for tag, steps, expect_out in (
        ("first", [{"gate": "Vorher freigeben?"}, seed()], None),
        ("middle", [seed(), {"gate": "Weiter?"},
                    {"llm.classify": {"id": "after", "labels": "NACHHER"}}], "NACHHER"),
        ("last", [seed(), {"llm.classify": {"id": "before", "labels": "VORHER"}},
                  {"gate": "Ergebnis abnehmen?"}], None),
    ):
        res = run_spec({"name": name(tag), "steps": steps})
        if not res.get("is_paused") or not res.get("resume_token"):
            record("FAIL", f"gate as {tag} step",
                   f"did not pause: {str(res)[:110]}")
            continue
        done = resume(res["resume_token"], res.get("run_id"), response={"approved": True})
        if not done.get("ok"):
            record("FAIL", f"gate as {tag} step", f"resume failed: {str(done)[:110]}")
        elif expect_out and expect_out not in str(done.get("output")):
            record("FAIL", f"gate as {tag} step",
                   f"resumed but the step after it did not run: {done.get('output')}")
        else:
            record("PASS", f"gate as {tag} step", "paused, resumed, ran on")


# --- the attribution question ------------------------------------------------

def case_two_gates_attribution() -> None:
    """Two gates, opposite answers: does each decision govern its own steps?

    The riskiest assumption in the partial-rerun build is that the n-th decision
    answers the n-th gate. It is decidable with the supported yes/no gates: say
    YES to the first and NO to the second. Correct attribution runs the step
    between the gates and skips the one behind the second. Swapped attribution
    does exactly the opposite - there is no reading where both look alike.
    """
    res = run_spec({"name": name("attribution"), "steps": [
        seed(),
        {"gate": {"id": "g1", "prompt": "Erste Frage"}},
        {"llm.classify": {"id": "between", "in": "seed", "labels": "ZWISCHEN"}},
        {"gate": {"id": "g2", "prompt": "Zweite Frage"}},
        {"llm.classify": {"id": "behind", "in": "seed", "labels": "DAHINTER"}},
    ]})
    if not res.get("is_paused"):
        record("FAIL", "two gates · attribution", f"first gate did not pause: {str(res)[:110]}")
        return
    run_id = res.get("run_id")
    mid = resume(res["resume_token"], run_id, response={"approved": True})
    if not mid.get("is_paused"):
        record("FAIL", "two gates · attribution",
               f"second gate did not pause after the first answer: {str(mid)[:110]}")
        return
    resume(mid["resume_token"], run_id, response={"approved": False})

    between = step_event(run_id, "between") if run_id else None
    behind = step_event(run_id, "behind") if run_id else None
    if between and not behind:
        record("PASS", "two gates · attribution",
               "yes governed the step after gate 1, no stopped the step after gate 2")
    elif behind and not between:
        record("FAIL", "two gates · attribution",
               "the answers are swapped - no ran the first gate's step, yes the second's")
    else:
        record("FAIL", "two gates · attribution",
               f"neither reading fits: between={bool(between)} behind={bool(behind)}")


def case_custom_schema_tail() -> None:
    """A gate with its own schema silently drops everything behind it.

    Every step after a gate compiles with condition $<gate>.response.approved
    (spec.py). A gate that answers with anything but that boolean - a word, a
    rating, the feedback a dotted {"from": "<gate>.<field>"} reference is meant
    to read - can never satisfy it, so the whole tail is skipped and the run
    still reports ok. Nothing anywhere says the work did not happen.
    """
    res = run_spec({"name": name("customschema"), "steps": [
        seed(),
        {"gate": {"id": "g", "prompt": "Ein Wort?", "schema": WORD_SCHEMA}},
        {"llm.classify": {"id": "tail", "in": "seed", "labels": "DAHINTER"}},
    ]})
    if not res.get("is_paused"):
        record("FAIL", "custom-schema gate · tail runs", f"no pause: {str(res)[:100]}")
        return
    run_id = res.get("run_id")
    done = resume(res["resume_token"], run_id, response={"word": "EINS"})
    tail = step_event(run_id, "tail") if run_id else None
    if tail:
        record("PASS", "custom-schema gate · tail runs", "the step behind the gate ran")
    else:
        record("FAIL", "custom-schema gate · tail runs",
               f"answered, run reports ok={done.get('ok')}, and the step behind the "
               "gate never ran - silently skipped by condition .response.approved")


# --- the decision must be in the record --------------------------------------

def case_decision_logged() -> None:
    res = run_spec({"name": name("logged"), "steps": [
        seed(), {"gate": "Freigeben?"},
        {"llm.classify": {"id": "after", "labels": "NACH"}},
    ]})
    run_id = res.get("run_id")
    if not res.get("is_paused") or not run_id:
        record("FAIL", "decision reaches the run log", f"no pause/run id: {str(res)[:100]}")
        return
    resume(res["resume_token"], run_id, response={"approved": True})
    decisions = [e for e in events(run_id)
                 if e.get("kind") == "gate_decision" or "gate_decision" in str(e.get("kind"))]
    if decisions:
        record("PASS", "decision reaches the run log",
               f"gate_decision recorded: {json.dumps(decisions[0], ensure_ascii=False)[:90]}")
    else:
        kinds = sorted({e.get("kind") for e in events(run_id)})
        record("FAIL", "decision reaches the run log",
               f"no gate_decision event; the run log only has {kinds}")


# --- a refusal must stop the work --------------------------------------------

def case_rejection() -> None:
    res = run_spec({"name": name("reject"), "steps": [
        seed(), {"gate": "Freigeben?"},
        {"llm.classify": {"id": "shouldnotrun", "labels": "GELAUFEN"}},
    ]})
    run_id = res.get("run_id")
    if not res.get("is_paused"):
        record("FAIL", "refusal stops the chain", f"no pause: {str(res)[:100]}")
        return
    done = resume(res["resume_token"], run_id, response={"approved": False})
    ran = step_event(run_id, "shouldnotrun") if run_id else None
    if ran is None and "GELAUFEN" not in str(done.get("output")):
        record("PASS", "refusal stops the chain", "the step behind the gate did not run")
    else:
        record("FAIL", "refusal stops the chain",
               f"the step behind a refused gate ran anyway: {str(done.get('output'))[:80]}")


# --- what the inbox actually sends -------------------------------------------

def case_inbox_path_for_content_gates() -> None:
    """The call the inbox actually makes for a gate that asks for content.

    ui/js/inbox.js builds a form from the response schema and posts
    {response: {...}} whenever gate_type is "input" - which is every gate this
    compiler emits, since it only ever writes `input:` gates. The {approve: true}
    fallback beside it belongs to `approval:` gates and is unreachable from a
    spec, so it is not tested here: a test of a call nobody makes reports
    failures nobody can hit.
    """
    res = run_spec({"name": name("inboxpath"), "steps": [
        seed(), {"gate": {"id": "g", "prompt": "Wort?", "schema": WORD_SCHEMA}},
        {"llm.classify": {"id": "tail", "in": "seed", "labels": "DAHINTER"}},
    ]})
    if not res.get("is_paused"):
        record("FAIL", "content gate · the inbox path works", f"no pause: {str(res)[:100]}")
        return
    run_id = res.get("run_id")
    done = resume(res["resume_token"], run_id, response={"word": "EINS"})
    tail = step_event(run_id, "tail") if run_id else None
    if done.get("ok") and tail:
        record("PASS", "content gate · the inbox path works",
               "answered with a word, and the work behind the gate ran")
    else:
        record("FAIL", "content gate · the inbox path works",
               f"ok={done.get('ok')}, tail ran={bool(tail)}")


def main() -> int:
    case_positions()
    case_two_gates_attribution()
    case_custom_schema_tail()
    case_decision_logged()
    case_rejection()
    case_inbox_path_for_content_gates()

    width = max(len(s) for _, s, _ in results)
    failed = sum(1 for v, _, _ in results if v == "FAIL")
    for verdict, subject, detail in results:
        print(f"{verdict:4}  {subject.ljust(width)}  {detail}")
    print(f"\n{len(results) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
