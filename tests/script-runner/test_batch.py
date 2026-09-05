#!/usr/bin/env python3
"""One spec, many argument sets: each a run of its own, all of them a group.

Offline, with a fake runner that answers ok, then pauses, then fails. What is
checked: every run's log names the batch and its place in it; a pause is
handed to the caller (the inbox) and the batch goes on; a failure counts and
does not stop the others; the endpoint answers at once and the status route
reads the group back from the logs.

    bash tests/script-runner/run-all.sh
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "lib" / "mora02_core" / "src"))
sys.path.insert(0, str(REPO / "apps" / "script-runner" / "app"))

_mp = types.ModuleType("python_multipart")
_mp.__version__ = "0.0.20"
_sub = types.ModuleType("python_multipart.multipart")
for _n in ("MultiPartParser", "QuerystringParser", "FormParser", "MultipartPart", "File", "Field"):
    setattr(_sub, _n, type(_n, (), {}))
_sub.parse_options_header = lambda *a, **k: (b"", {})
_mp.multipart = _sub
sys.modules.setdefault("python_multipart", _mp)
sys.modules.setdefault("python_multipart.multipart", _sub)

DATA = Path(tempfile.mkdtemp(prefix="sr-batch-"))
os.environ["MORA02_SCRIPT_RUNNER_DATA"] = str(DATA)
os.environ["MORA02_PIPELINE_LOG_DIR"] = str(DATA / "logs")
os.environ["MORA02_PIPELINE_BUCKET_DIR"] = str(DATA / "bucket")
os.environ["MORA02_PIPELINE_WORKSPACE"] = str(DATA / "ws")
os.environ.pop("MORA02_RUN_FAILURE_NOTIFY", None)

import httpx  # noqa: E402
import main  # noqa: E402
import pipelines  # noqa: E402
from mora02_core import pipeline  # noqa: E402
from mora02_core.pipeline import runlog  # noqa: E402
from mora02_core.pipeline.base import PipelineResult  # noqa: E402

results: list[tuple[str, str, str]] = []
SPEC = {"name": "batch-probe", "steps": [{"web.fetch": {"id": "seed", "in": "none", "url": "http://x"}}]}


def record(ok: bool, subject: str, detail: str = "") -> None:
    results.append(("ok" if ok else "FAIL", subject, detail))


class Script:
    """The fake runner's answers, in order: ok, paused, failed, then ok."""
    answers = [
        PipelineResult(ok=True, status="ok", runner="fake"),
        PipelineResult(ok=True, status="needs_input", runner="fake", resume_token="secret",
                       requires_input={"prompt": "go on?"}),
        PipelineResult(ok=False, status="error", runner="fake", error={"message": "boom"}),
    ]
    seen_args: list = []

    @classmethod
    async def run(cls, path, args=None, runner=None):
        cls.seen_args.append(args)
        return cls.answers[(len(cls.seen_args) - 1) % len(cls.answers)]


def main_() -> int:
    pipeline.run_pipeline = Script.run
    filed: list = []

    async def on_result(res):
        if res.is_paused:
            filed.append(res.run_id)

    summary = asyncio.run(pipeline.run_pipeline_batch(
        SPEC, [{"subject": "a"}, {"subject": "b"}, {"subject": "c"}], runner="fake",
        trigger="manual", on_result=on_result))
    record(summary["size"] == 3 and len(summary["runs"]) == 3, "three argument sets make three runs",
           f"{len(summary['runs'])} runs")
    record(Script.seen_args == [{"subject": "a"}, {"subject": "b"}, {"subject": "c"}],
           "in the order given, each with its own arguments", str(Script.seen_args))
    record((summary["ok"], summary["paused"], summary["failed"]) == (1, 1, 1),
           "the summary counts ok, paused and failed", f"{summary['ok']}/{summary['paused']}/{summary['failed']}")
    record(summary["runs"][2]["run_id"] is not None, "a failed run keeps its run id and the batch went on")
    starts = []
    for r in summary["runs"]:
        st = next((e for e in runlog.read_events(r["run_id"]) if e.get("kind") == "run_start"), {})
        starts.append(st.get("batch") or {})
    record(all(b.get("id") == summary["batch_id"] for b in starts) and [b.get("index") for b in starts] == [1, 2, 3]
           and all(b.get("size") == 3 for b in starts),
           "every run's log names the batch, its index and the size", str(starts)[:90])
    record(filed == [summary["runs"][1]["run_id"]], "the paused run, and only it, was handed to the caller to file",
           str(filed))
    record(summary["batch_id"].startswith("batch_"), "a batch id is recognisable as not a run id", summary["batch_id"])

    # --- the endpoint answers at once; the status route reads the group back --
    Script.seen_args.clear()
    real_pilot = pipelines._PILOT_URL
    pipelines._PILOT_URL = "http://127.0.0.1:9"  # nothing listens: filing fails, the batch must not

    async def via_http():
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t", timeout=30) as c:
            r = await c.post("/pipeline/run-batch", json={"spec": SPEC, "runner": "fake",
                                                          "arg_sets": [{"subject": "x"}, {"subject": "y"}]})
            first = r.json()
            await asyncio.sleep(0.3)  # the background task runs on this loop
            s = await c.get(f"/pipeline/batch/{first.get('batch_id', 'batch_none')}")
            bad = await c.post("/pipeline/run-batch", json={"spec": SPEC, "arg_sets": []})
            walk = await c.get("/pipeline/batch/batch_..%2Fetc")
            return r.status_code, first, s.status_code, s.json(), bad.status_code, walk.status_code

    try:
        code, first, scode, status, bad, walk = asyncio.run(via_http())
    finally:
        pipelines._PILOT_URL = real_pilot
    record(code == 200 and first.get("status") == "started" and first.get("size") == 2,
           "POST /pipeline/run-batch answers at once with the batch id", str(first)[:80])
    record(scode == 200 and status.get("started") == 2 and status.get("size") == 2,
           "GET /pipeline/batch/{id} lists the runs of the group", f"started={status.get('started')} size={status.get('size')}")
    record(status.get("done") == 1 and status.get("paused") == 1,
           "and counts their fates", f"done={status.get('done')} paused={status.get('paused')} failed={status.get('failed')}")
    record(bad == 400, "an empty batch is refused", str(bad))
    record(walk in (404, 422), "a batch id that walks is refused", str(walk))

    width = max(len(s) for _, s, _ in results)
    failed = 0
    for verdict, subject, detail in results:
        failed += verdict == "FAIL"
        print(f"[ {verdict:^4} ] {subject.ljust(width)}  {detail}")
    print(f"\n{len(results) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main_())
