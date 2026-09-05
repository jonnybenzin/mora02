#!/usr/bin/env python3
"""A failed run tells the person - and only a failed one, and never a test.

Offline: notify is replaced by a recorder, the run log lives in a temp
directory. The six answers that decide whether this is useful rather than
noisy: the message names the step and its error; a run marked as a test is
silent; an unset channel is silent; a run that succeeded is silent; a missing
recipient is recorded in the log instead of raising; a send that fails is
recorded too and never becomes a second failure.

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

DATA = Path(tempfile.mkdtemp(prefix="sr-failnotify-"))
os.environ["MORA02_PIPELINE_LOG_DIR"] = str(DATA / "logs")
os.environ["MORA02_PIPELINE_BUCKET_DIR"] = str(DATA / "bucket")
os.environ["MORA02_PIPELINE_WORKSPACE"] = str(DATA / "ws")

from mora02_core import pipeline  # noqa: E402
from mora02_core.notify import NotifyError  # noqa: E402
from mora02_core.pipeline import runlog  # noqa: E402
from mora02_core.pipeline.base import PipelineResult  # noqa: E402

results: list[tuple[str, str, str]] = []


def record(ok: bool, subject: str, detail: str = "") -> None:
    results.append(("ok" if ok else "FAIL", subject, detail))


class Recorder:
    calls: list = []
    raise_with: Exception | None = None

    @classmethod
    async def notify(cls, channel, target, message, **kw):
        cls.calls.append({"channel": channel, "target": target, "message": message, **kw})
        if cls.raise_with:
            raise cls.raise_with


def failed_run(rid: str, trigger: str = "manual") -> None:
    runlog.log_event(rid, "run_start", pipeline="demo-flow", trigger=trigger, spec={"steps": []})
    runlog.log_event(rid, "step", step_id="picture", op="image.generate", status="failed",
                     error="ComfyUI answered 500", duration_ms=12)
    runlog.log_event(rid, "run_result", status="error", ok=False)


def notified(rid: str) -> list[dict]:
    return [e for e in runlog.read_events(rid) if e.get("kind") == "notified"]


def main() -> int:
    pipeline.notify = Recorder.notify
    FAILED = PipelineResult(ok=False, status="error", runner="fake")
    OK = PipelineResult(ok=True, status="ok", runner="fake")

    # --- the message names flow, run, step and error ---------------------------
    os.environ["MORA02_RUN_FAILURE_NOTIFY"] = "email"
    os.environ["MORA02_EMAIL_TARGET"] = "me@example"
    rid = "20260905_120000_fail0001"
    failed_run(rid)
    asyncio.run(pipeline.report_run_failure(rid, FAILED))
    call = Recorder.calls[-1] if Recorder.calls else {}
    record(bool(call) and call["channel"] == "email" and call["target"] == "me@example",
           "a failed run is reported on the configured channel to its target",
           f"{call.get('channel')} -> {call.get('target')}")
    msg = call.get("message", "")
    record("demo-flow" in msg and rid in msg and "picture" in msg and "ComfyUI answered 500" in msg,
           "and the message names the flow, the run, the failing step and its error", msg.replace("\n", " | ")[:100])
    record(any(e.get("ok") for e in notified(rid)), "the act is written into the run log as `notified`")

    # --- silent cases ------------------------------------------------------------
    n = len(Recorder.calls)
    rid2 = "20260905_120000_fail0002"
    failed_run(rid2, trigger="test")
    asyncio.run(pipeline.report_run_failure(rid2, FAILED))
    record(len(Recorder.calls) == n, "a run marked as a test is never reported", "silent")
    asyncio.run(pipeline.report_run_failure(rid, OK))
    record(len(Recorder.calls) == n, "a run that succeeded is not reported", "silent")
    os.environ["MORA02_RUN_FAILURE_NOTIFY"] = ""
    asyncio.run(pipeline.report_run_failure(rid, FAILED))
    record(len(Recorder.calls) == n, "without a configured channel nothing is sent", "silent")
    os.environ["MORA02_RUN_FAILURE_NOTIFY"] = "signal"
    os.environ.pop("MORA02_SIGNAL_TARGET", None)
    rid3 = "20260905_120000_fail0003"
    failed_run(rid3)
    asyncio.run(pipeline.report_run_failure(rid3, FAILED))
    bad = [e for e in notified(rid3) if not e.get("ok")]
    record(len(Recorder.calls) == n and bad and "MORA02_SIGNAL_TARGET" in bad[0].get("error", ""),
           "a missing recipient is recorded in the log, naming the variable", (bad[0].get("error") if bad else "")[:60])

    # --- a send that fails does not become a second failure ---------------------
    os.environ["MORA02_RUN_FAILURE_NOTIFY"] = "email"
    Recorder.raise_with = NotifyError("smtp down")
    rid4 = "20260905_120000_fail0004"
    failed_run(rid4)
    try:
        asyncio.run(pipeline.report_run_failure(rid4, FAILED))
        raised = False
    except Exception:
        raised = True
    Recorder.raise_with = None
    bad = [e for e in notified(rid4) if not e.get("ok")]
    record(not raised and bad and "smtp down" in bad[0].get("error", ""),
           "a send that fails is logged and swallowed", (bad[0].get("error") if bad else "raised")[:60])

    # --- the hook sits in the real run path ----------------------------------------
    real_run = pipeline.run_pipeline

    async def failing_run(path, args=None, runner=None):
        # the runner would have logged the step; here the log gets it by hand
        return PipelineResult(ok=False, status="error", runner="fake",
                              error={"message": "the runner gave up"})

    pipeline.run_pipeline = failing_run
    n = len(Recorder.calls)
    try:
        res = asyncio.run(pipeline.run_pipeline_spec(
            {"name": "hooked", "steps": [{"web.fetch": {"id": "seed", "in": "none", "url": "http://x"}}]},
            runner="fake", trigger="manual"))
    finally:
        pipeline.run_pipeline = real_run
    record(len(Recorder.calls) == n + 1 and res.run_id in Recorder.calls[-1]["message"],
           "run_pipeline_spec reports a failed run on its own", Recorder.calls[-1]["message"].replace("\n", " | ")[:90] if len(Recorder.calls) > n else "no call")
    record("no step reported a failure" in Recorder.calls[-1]["message"] if len(Recorder.calls) > n else False,
           "and says so when no step wrote a failure of its own")

    width = max(len(s) for _, s, _ in results)
    failed = 0
    for verdict, subject, detail in results:
        failed += verdict == "FAIL"
        print(f"[ {verdict:^4} ] {subject.ljust(width)}  {detail}")
    print(f"\n{len(results) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
