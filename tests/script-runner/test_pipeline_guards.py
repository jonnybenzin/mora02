#!/usr/bin/env python3
"""The five library repairs of review 4, each pinned by the case that found it.

  1. an inline spec's name cannot leave the workspace
  2. two runs of one flow compile to two files
  3. a re-run matches gate decisions by id, never by position
  4. a gate's answer is in the bucket while the resumed leg runs
  6. a gate schema that is not an object is refused at parse time

Offline: fake runners, temp directories, no docker.

    bash tests/script-runner/run-all.sh
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "lib" / "mora02_core" / "src"))

DATA = Path(tempfile.mkdtemp(prefix="sr-guards-"))
WS = DATA / "ws"
os.environ["MORA02_PIPELINE_LOG_DIR"] = str(DATA / "logs")
os.environ["MORA02_PIPELINE_BUCKET_DIR"] = str(DATA / "bucket")
os.environ["MORA02_PIPELINE_WORKSPACE"] = str(WS)
os.environ.pop("MORA02_RUN_FAILURE_NOTIFY", None)

from mora02_core import pipeline  # noqa: E402
from mora02_core.pipeline import PipelineError, runbucket, runlog, spec  # noqa: E402
from mora02_core.pipeline.base import PipelineResult  # noqa: E402
from mora02_core.pipeline.registry import register_runner  # noqa: E402

results: list[tuple[str, str, str]] = []
STEP = {"web.fetch": {"id": "seed", "in": "none", "url": "http://x"}}


def record(ok: bool, subject: str, detail: str = "") -> None:
    results.append(("ok" if ok else "FAIL", subject, detail))


def refuses(fn, subject: str, needle: str = "") -> None:
    try:
        fn()
        record(False, subject, "accepted")
    except PipelineError as e:
        record(needle in str(e), subject, str(e)[:80])


def main() -> int:
    seen: dict = {}

    async def fake_run(path, args=None, runner=None):
        seen.setdefault("paths", []).append(path)
        return PipelineResult(ok=True, status="ok", runner="fake")

    pipeline.run_pipeline = fake_run

    # --- 1. the name is checked at the parser, so every door gets the rule ----
    for bad in ("../escaped/pwned", "/abs/olute", "Has Space", "t", "UPPER"):
        refuses(lambda: spec.load_spec({"name": bad, "steps": [STEP]}),
                f"spec name {bad!r} is refused at parse time", "flow name")
    refuses(lambda: asyncio.run(pipeline.run_pipeline_spec({"name": "../escaped/x", "steps": [STEP]}, runner="fake")),
            "and run_pipeline_spec refuses it before any file is written", "flow name")
    record(not (DATA / "escaped").exists() and not seen.get("paths"),
           "nothing was written outside the workspace and no runner was called")

    # --- 2. one compiled file per run ---------------------------------------
    good = {"name": "same-flow", "steps": [STEP]}
    a = asyncio.run(pipeline.run_pipeline_spec(good, runner="fake"))
    b = asyncio.run(pipeline.run_pipeline_spec(good, runner="fake"))
    paths = seen["paths"]
    record(len(set(paths)) == 2 and all(Path(p).is_file() for p in paths),
           "two runs of one flow compile to two files that both still exist",
           " / ".join(Path(p).name for p in paths))
    record(a.run_id in paths[0] and b.run_id in paths[1], "and each file carries its run id")
    record(all(Path(p).resolve().is_relative_to(WS.resolve()) for p in paths), "inside the workspace")

    # --- 4. the gate's answer is in the bucket while the resumed leg runs ------
    class Resumer:
        name = "resumer"

        async def run(self, *a, **k):
            return PipelineResult(ok=True, status="ok", runner="resumer")

        async def resume(self, token, **kw):
            try:
                seen["during"] = runbucket.get("R4", "review.feedback")
            except KeyError:
                seen["during"] = "<not there>"
            return PipelineResult(ok=True, status="ok", runner="resumer")

    register_runner(Resumer())
    runlog.log_event("R4", "run_start", pipeline="p", trigger="test",
                     spec={"name": "probe-flow", "steps": [STEP, {"review": {"id": "review", "prompt": "ok?"}}]})
    asyncio.run(pipeline.resume_pipeline("tok", approve=True, response={"feedback": "make it bluer"},
                                         runner="resumer", run_id="R4"))
    record(seen.get("during") == "make it bluer",
           "a step in the resumed leg can read the gate's answer", str(seen.get("during")))
    dec = [e for e in runlog.read_events("R4") if e.get("kind") == "gate_decision"]
    record(bool(dec) and dec[-1].get("gate_id") == "review",
           "and the decision is logged under the gate's id", str(dec[-1].get("gate_id") if dec else None))

    # --- 3. a re-run matches decisions by id --------------------------------
    src = {"name": "two-gates", "steps": [STEP, {"gate": {"id": "ga", "prompt": "a?"}},
                                          {"llm.complete": {"id": "mid", "prompt": "x"}},
                                          {"gate": {"id": "gb", "prompt": "b?"}}]}
    runlog.log_event("SRC", "run_start", pipeline="two-gates", trigger="test", spec=src)
    runlog.log_event("SRC", "gate_decision", gate_id="ga", decision="approve")
    runlog.log_event("SRC", "gate_decision", gate_id="gb", decision="reject")
    revised = spec.load_spec({"name": "two-gates", "steps": [STEP, {"llm.complete": {"id": "mid", "prompt": "x"}},
                                                             {"gate": {"id": "gb", "prompt": "b?"}}]})
    refuses(lambda: pipeline._guard_reused_gates(revised, ["gb"], "SRC"),
            "dropping a gate in the revision cannot turn the next gate's rejection into an approval", "reject")
    # an OLD log without gate ids: positions count against the SOURCE spec
    runlog.log_event("OLD", "run_start", pipeline="two-gates", trigger="test", spec=src)
    runlog.log_event("OLD", "gate_decision", decision="approve")
    runlog.log_event("OLD", "gate_decision", decision="reject")
    refuses(lambda: pipeline._guard_reused_gates(revised, ["gb"], "OLD"),
            "an older log is paired against the source run's own gate order", "reject")
    try:
        pipeline._guard_reused_gates(revised, [], "OLD")
        record(True, "and reusing no gate at all is still fine")
    except PipelineError as e:
        record(False, "and reusing no gate at all is still fine", str(e)[:60])
    runlog.log_event("NOSPEC", "gate_decision", decision="approve")
    refuses(lambda: pipeline._guard_reused_gates(revised, ["gb"], "NOSPEC"),
            "a source log without a recorded spec cannot vouch for any gate", "records no spec")

    # --- 6. a gate schema that is not an object ------------------------------
    for shape in ("nope", ["a"], 7):
        refuses(lambda: spec.load_spec({"name": "gate-probe", "steps": [STEP, {"gate": {"prompt": "ok?", "schema": shape}}, STEP | {}]}),
                f"gate schema {type(shape).__name__} is refused at parse time", "schema must be an object")
    refuses(lambda: spec.load_spec({"name": "gate-probe", "steps": [STEP, {"review": {"prompt": "ok?", "schema": "nope"}}]}),
            "and so is a review's", "schema must be an object")
    problems, _ = spec.check_flow({"name": "gate-probe", "steps": [STEP, {"gate": {"prompt": "ok?", "schema": "nope"}}]})
    record(bool(problems) and "schema" in problems[0], "flow_check reports it instead of saying ok", str(problems)[:70])
    weird = spec.load_spec({"name": "gate-probe", "steps": [STEP, {"gate": {"prompt": "ok?", "schema": {"properties": "x"}}},
                                                   {"llm.complete": {"id": "after", "prompt": "x"}}]})
    try:
        spec.compile_to_lobster(weird, run_id="20260905_000000_deadbeef")
        record(True, "an object schema with odd properties still compiles")
    except Exception as e:
        record(False, "an object schema with odd properties still compiles", f"{type(e).__name__}: {e}"[:70])

    width = max(len(s) for _, s, _ in results)
    failed = 0
    for verdict, subject, detail in results:
        failed += verdict == "FAIL"
        print(f"[ {verdict:^4} ] {subject.ljust(width)}  {detail}")
    print(f"\n{len(results) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
