#!/usr/bin/env python3
"""Phase 2 of the vocabulary test plan: when something fails, does a human find out?

The nine defects of 26 August 2026 were not mostly crashes. They were failures
that arrived as "error 400" with the reason thrown away, or as a value that had
quietly lost half of itself. So every case here provokes one specific failure and
then asks the same question on three levels, because a reason that exists in only
one of them is a reason nobody reads:

  HTTP   does the response body NAME the cause, or just carry a status code?
  LOG    does the run log record the step as failed, with the reason?
  RUNS   does /pipeline/run/<id> - what the RUNS view renders - carry it through?

A case may legitimately have no LOG/RUNS level (a request refused before a run
exists). That is recorded as "n/a", not as a pass, so the gap stays visible.

Usage:
    python3 tests/pipeline/test_errorpaths.py
    python3 tests/pipeline/test_errorpaths.py --slow   # include the LLM cases

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

results: list[tuple[str, str, str]] = []


def record(verdict: str, subject: str, detail: str) -> None:
    results.append((verdict, subject, detail))


def _request(method: str, url: str, body: bytes | None = None,
             ctype: str = "text/plain; charset=utf-8") -> tuple[int, str]:
    req = urllib.request.Request(url, data=body, method=method,
                                 headers={"Content-Type": ctype})
    try:
        with urllib.request.urlopen(req, timeout=240) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # connection refused, timeout, ...
        return 0, f"{type(e).__name__}: {e}"


def step(op: str, body: str = "", query: str = "") -> tuple[int, str]:
    return _request("POST", f"{RUNNER}/pipeline/step/{op}?{query}", body.encode("utf-8"))


def run_spec(spec: dict) -> tuple[int, str]:
    return _request("POST", f"{RUNNER}/pipeline/run-spec",
                    json.dumps({"spec": spec}).encode("utf-8"), "application/json")


def log_events(run_id: str) -> list[dict]:
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


def runs_view(run_id: str) -> dict:
    status, body = _request("GET", f"{RUNNER}/pipeline/run/{run_id}")
    if status != 200:
        return {}
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {}


def check_case(name: str, op: str, body: str, query: str, expect: list[str],
               run_id: str | None = None, step_id: str = "boom") -> None:
    """Provoke one step failure and audit all three levels of visibility."""
    q = query
    if run_id:
        q = f"{q}&run_id={run_id}&step_id={step_id}" if q else f"run_id={run_id}&step_id={step_id}"
    status, resp = step(op, body, q)

    # HTTP: refused, and the body says why.
    named = [w for w in expect if w.lower() in resp.lower()]
    if status == 0:
        record("FAIL", f"{name} · HTTP", f"no response: {resp[:90]}")
    elif 200 <= status < 300:
        record("FAIL", f"{name} · HTTP", f"accepted with {status} - the failure was not refused")
    elif named:
        record("PASS", f"{name} · HTTP", f"{status}, names the cause ({named[0]!r})")
    else:
        record("FAIL", f"{name} · HTTP",
               f"{status}, but the cause is not named: {resp[:110]}")

    if not run_id:
        record("n/a", f"{name} · LOG", "refused before a run exists - nothing to log")
        record("n/a", f"{name} · RUNS", "refused before a run exists - nothing to show")
        return

    events = [e for e in log_events(run_id)
              if e.get("kind") == "step" and e.get("step_id") == step_id]
    if not events:
        record("FAIL", f"{name} · LOG", "no step event written for the failure")
    elif events[0].get("status") != "failed":
        record("FAIL", f"{name} · LOG", f"logged as {events[0].get('status')!r}, not failed")
    elif not events[0].get("error"):
        record("FAIL", f"{name} · LOG", "logged as failed but without a reason")
    else:
        record("PASS", f"{name} · LOG", f"failed + reason: {events[0]['error'][:70]}")

    view = runs_view(run_id)
    steps = [s for s in view.get("steps", []) if s.get("step_id") == step_id]
    if not steps:
        record("FAIL", f"{name} · RUNS", "the run view does not list the failed step")
    elif steps[0].get("status") != "failed" or not steps[0].get("error"):
        record("FAIL", f"{name} · RUNS",
               f"listed as {steps[0].get('status')!r}, error={steps[0].get('error')!r}")
    else:
        record("PASS", f"{name} · RUNS", f"visible with reason: {steps[0]['error'][:70]}")


def _planned_op() -> str | None:
    """An op the vocabulary catalogues but has no handler for - it must not compile."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib/mora02_core/src"))
    try:
        from mora02_core.pipeline import vocab
    except ImportError:
        return None
    return next((o.name for o in vocab.all_ops() if o.status != "wired"), None)


def rid(tag: str) -> str:
    return f"test-errorpath-{tag}-{int(time.time())}"


def main() -> int:
    slow = "--slow" in sys.argv

    # --- 1. an op that does not exist, called directly -----------------------
    status, resp = step("does.not.exist", "hello")
    ok = status == 404 and "does.not.exist" in resp
    record("PASS" if ok else "FAIL", "unknown op (direct) · HTTP",
           f"{status}: {resp[:90]}")
    record("n/a", "unknown op (direct) · LOG", "no handler, no run - nothing to log")

    # --- 2. an op that does not exist, inside a spec -------------------------
    status, resp = run_spec({
        "name": "errorpath-unknown-op",
        "steps": [{"llm.nonexistent": {"id": "a", "prompt": "hi"}}],
    })
    named = "llm.nonexistent" in resp or "unknown" in resp.lower()
    record("PASS" if status >= 400 and named else "FAIL", "unknown op (spec) · COMPILE",
           f"{status}: {resp[:110]}")

    # --- 3. a step wired to an id that does not exist ------------------------
    status, resp = run_spec({
        "name": "errorpath-dangling-wire",
        "steps": [
            {"llm.complete": {"id": "a", "prompt": "hi"}},
            {"notify": {"id": "b", "in": "ghost", "target": "+490000000000"}},
        ],
    })
    named = "ghost" in resp
    record("PASS" if status >= 400 and named else "FAIL", "wire to unknown step · COMPILE",
           f"{status}: {resp[:110]}")

    # --- 4. missing required parameter ---------------------------------------
    r = rid("noparam")
    check_case("missing required param", "db.query", "", "", ["table"], run_id=r)

    # --- 5. an asset ref pointing at nothing ---------------------------------
    r = rid("ghostref")
    check_case("asset ref into nowhere", "image.cutout",
               "asset://comfyui/definitely-not-here-7q4x.png", "",
               ["not", "definitely-not-here"], run_id=r)

    # --- 6. type misuse: a text value where an image ref belongs -------------
    r = rid("typemix")
    check_case("text into image.edit", "image.edit",
               "this is prose, not a picture", "prompt=make%20it%20blue",
               ["image.edit", "ref"], run_id=r)

    # --- 7. fan-in naming a step that never ran ------------------------------
    r = rid("collect")
    check_case("fan-in on unknown id", "clip.generate", "", "__collect=neverran",
               ["neverran", "bucket"], run_id=r)

    # --- 8. a ref param pointing at a step that never ran --------------------
    r = rid("refparam")
    check_case("param ref on unknown id", "image.generate", "",
               "__ref_prompt=neverran", ["neverran", "bucket"], run_id=r)

    # --- 8b. a step whose op is catalogued but not built ----------------------
    planned = _planned_op()
    if planned:
        status, resp = run_spec({
            "name": "errorpath-planned-op",
            "steps": [{planned: {"id": "a"}}],
        })
        named = planned in resp and "planned" in resp.lower()
        record("PASS" if status >= 400 and named else "FAIL", "planned op · COMPILE",
               f"{status}: {resp[:110]}")
    else:
        record("n/a", "planned op · COMPILE", "no planned op left in the vocabulary")

    # --- 8c. an upstream that does not answer --------------------------------
    # The real "ComfyUI is down" case needs a container stopped by hand. What can
    # be provoked from here has the same shape: an op whose target lives in the
    # request rather than in the container's environment. It answers the question
    # that matters - does a dead upstream come back with a REASON, or with a bare
    # status code, the way curl -fsS used to hand one over?
    r = rid("refused")
    check_case("upstream refuses connection", "web.fetch", "",
               "url=http%3A%2F%2F127.0.0.1%3A9%2F",
               ["connect", "refused", "connection"], run_id=r)

    r = rid("nohost")
    check_case("upstream host does not exist", "web.fetch", "",
               "url=http%3A%2F%2Fno-such-host-7q4x.invalid%2F",
               ["resolve", "name", "connect", "getaddrinfo"], run_id=r)

    # --- 8d. a path into a structure that does not go there -------------------
    # data.pick is the joint between a step that emits a structure and one that
    # wants a single value out of it. A path that misses must say what IS there,
    # or the author is left guessing at a shape they cannot see.
    r = rid("badpath")
    check_case("path into nothing", "data.pick", '{"results": [{"url": "x"}]}',
               "path=results.0.href", ["href", "url"], run_id=r)

    r = rid("notjson")
    check_case("data.pick on plain prose", "data.pick", "kein JSON, nur Text",
               "path=a.b", ["json"], run_id=r)

    # --- 8e. an op that names one of its log fields badly ---------------------
    # A handler may attach its own fields to the run log. If one of them collides
    # with a field the endpoint already writes, the merge used to raise AFTER the
    # handler had run and outside its try block: the work was done, the value was
    # in the bucket, and the caller got a bare 500 with no reason. Found by
    # writing an op that used "kind".
    r = rid("clash")
    status, resp = step("data.pick", '{"a": {"b": "value"}}',
                        f"path=a.b&run_id={r}&step_id=clash&fmt=out")
    if status == 200 and resp.strip() == "value":
        record("PASS", "a reserved log field does not kill the step",
               "the step answered normally")
    else:
        record("FAIL", "a reserved log field does not kill the step",
               f"HTTP {status}: {resp[:100]}")

    # --- 9. a flow that does not exist ---------------------------------------
    status, resp = _request("GET", f"{RUNNER}/pipeline/flow/no-such-flow-7q4x")
    record("PASS" if status == 404 and "no-such-flow" in resp else "FAIL",
           "unknown flow · HTTP", f"{status}: {resp[:90]}")

    # --- 10. a completion cut short by max_tokens ----------------------------
    # Not an error path in the HTTP sense - the step succeeds. But a story that
    # stops mid-sentence looks like the model gave up, so the cut must travel all
    # the way to the human. This is defect 5 and 7 of 26 August, end to end.
    if slow:
        r = rid("cut")
        status, _ = step("llm.complete", "",
                         f"prompt=Schreib%20einen%20langen%20Essay&max_tokens=1"
                         f"&run_id={r}&step_id=cut")
        events = [e for e in log_events(r)
                  if e.get("kind") == "step" and e.get("step_id") == "cut"]
        if events and events[0].get("truncated"):
            record("PASS", "cut completion · LOG",
                   f"flagged: {events[0].get('hint', '')[:60]}")
        else:
            record("FAIL", "cut completion · LOG", "no truncation flag on the step event")

        view = runs_view(r)
        vsteps = [x for x in view.get("steps", []) if x.get("step_id") == "cut"]
        if vsteps and vsteps[0].get("truncated"):
            record("PASS", "cut completion · RUNS", "warning reaches the run view")
        else:
            record("FAIL", "cut completion · RUNS",
                   "run view drops the flag - the UI renders s.truncated, the API "
                   "never sends it")
    else:
        record("n/a", "cut completion", "skipped - run with --slow")

    # An empty completion cannot be provoked from outside: every prompt that
    # reaches the model returns at least one token. The guard is read in the
    # static audit instead; forcing it at runtime would need a stubbed model.
    record("n/a", "empty LLM answer", "not forceable without stubbing the model")

    width = max(len(s) for _, s, _ in results)
    failed = sum(1 for v, _, _ in results if v == "FAIL")
    na = sum(1 for v, _, _ in results if v == "n/a")
    for verdict, subject, detail in results:
        print(f"{verdict:4}  {subject.ljust(width)}  {detail}")
    print(f"\n{len(results) - failed - na} passed, {failed} failed, {na} not applicable")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
