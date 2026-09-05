#!/usr/bin/env python3
"""The run log says what a run produced, who started it, and how it ended.

Offline: a fake runner and a temp data directory, no GPU, no gateway. What is
checked is the log itself - the JSONL the Runs view and pipelog read - because
that is what a person consults when a run is questioned weeks later:

  - an output FILE is described (bytes, checksum, dimensions), not just named
  - a run can be archived into one folder: files, text outputs, log, bucket
  - a resumed run records its fate, not only the pause it came back from
  - run_start says who triggered it and which vocabulary it compiled against
  - the scheduler's one-step publish flow compiles and wires its args

    bash tests/script-runner/run-all.sh
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import types
import zlib
import struct
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "lib" / "mora02_core" / "src"))
sys.path.insert(0, str(REPO / "apps" / "script-runner" / "app"))

# python-multipart stub, as in the sibling suites: the upload route needs the
# package at import time and this python may not have it.
_mp = types.ModuleType("python_multipart")
_mp.__version__ = "0.0.20"
_sub = types.ModuleType("python_multipart.multipart")
for _n in ("MultiPartParser", "QuerystringParser", "FormParser", "MultipartPart",
           "File", "Field"):
    setattr(_sub, _n, type(_n, (), {}))
_sub.parse_options_header = lambda *a, **k: (b"", {})
_mp.multipart = _sub
sys.modules.setdefault("python_multipart", _mp)
sys.modules.setdefault("python_multipart.multipart", _sub)

DATA = Path(tempfile.mkdtemp(prefix="sr-execlog-"))
LOGS = DATA / "logs"
STORE = DATA / "comfyui"
STORE.mkdir(parents=True)
os.environ["MORA02_SCRIPT_RUNNER_DATA"] = str(DATA)
os.environ["MORA02_PIPELINE_LOG_DIR"] = str(LOGS)
os.environ["MORA02_PIPELINE_BUCKET_DIR"] = str(DATA / "bucket")
os.environ["MORA02_PIPELINE_WORKSPACE"] = str(DATA / "workspace")
os.environ["MORA02_ASSET_STORE_COMFYUI"] = str(STORE)

import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from mora02_core import pipeline  # noqa: E402
from mora02_core.pipeline import runbucket, runlog  # noqa: E402
from mora02_core.pipeline.base import PipelineResult  # noqa: E402
from mora02_core.pipeline.registry import register_runner  # noqa: E402

results: list[tuple[str, str, str]] = []


def record(ok: bool, subject: str, detail: str = "") -> None:
    results.append(("ok" if ok else "FAIL", subject, detail))


def _png(width: int, height: int) -> bytes:
    """A valid PNG without Pillow: one IDAT of grey pixels."""
    def chunk(tag, body):
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"\x80" * (width * 3) for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _events(run_id: str) -> list[dict]:
    return runlog.read_events(run_id)


def main_() -> int:
    client = TestClient(main.app)

    # --- an output file is described, not just named --------------------------
    png = _png(8, 6)
    (STORE / "probe_000.png").write_bytes(png)
    rid = "20260905_100000_execlog1"
    r = client.post(f"/pipeline/step/source.file?store=comfyui&pick=latest&run_id={rid}&step_id=pic")
    record(r.status_code == 200, "a source.file step runs against the temp store", f"HTTP {r.status_code}")
    step = next((e for e in _events(rid) if e.get("kind") == "step"), {})
    facts = step.get("out_file") or {}
    record(facts.get("bytes") == len(png) and facts.get("sha256") == hashlib.sha256(png).hexdigest(),
           "the step event carries the file's size and checksum",
           f"bytes={facts.get('bytes')} sha256={str(facts.get('sha256'))[:12]}")
    record((facts.get("width"), facts.get("height")) == (8, 6),
           "and its pixel dimensions", f"{facts.get('width')}x{facts.get('height')}")
    # a direct step call (no run) does not compute facts and does not log
    r = client.post("/pipeline/step/source.file?store=comfyui&pick=latest")
    record(r.status_code == 200 and "out_file" not in r.json(),
           "a step called outside a run stays as it was", str(list(r.json()))[:60])

    # --- archive: one folder with everything the run produced ------------------
    runbucket.put(rid, "caption", "hello world")
    runbucket.put(rid, "ghost", "asset://comfyui/never_there.png")
    r = client.post(f"/pipeline/run/{rid}/archive")
    record(r.status_code == 200, "archive answers", f"HTTP {r.status_code} {r.text[:80]}")
    m = r.json() if r.status_code == 200 else {}
    dest = LOGS / rid
    copied = dest / "pic__probe_000.png"
    record(copied.is_file() and copied.read_bytes() == png,
           "the picture is copied under <step_id>__<file>", copied.name)
    record((dest / "caption.txt").read_text(encoding="utf-8") == "hello world",
           "a text output becomes <step_id>.txt")
    record((dest / f"{rid}.jsonl").is_file() and (dest / "bucket.json").is_file()
           and (dest / "manifest.json").is_file(),
           "log, bucket and manifest travel with it")
    record(m.get("missing") == 1 and any(f.get("missing") for f in m.get("files", [])),
           "a ref whose file is gone is listed as missing, not silently skipped",
           f"missing={m.get('missing')}")
    record(any(e.get("kind") == "run_archived" for e in _events(rid)),
           "and the archive itself is an event in the run log")
    r = client.post("/pipeline/run/../etc/archive")
    record(r.status_code in (404, 422), "a run id that walks is refused", f"HTTP {r.status_code}")

    # --- a resumed run records its fate ----------------------------------------
    class FakeRunner:
        name = "fake"

        async def run(self, *a, **k):
            return PipelineResult(ok=True, status="ok", runner="fake")

        async def resume(self, *a, **k):
            return PipelineResult(ok=True, status="ok", runner="fake")

    register_runner(FakeRunner())
    rid2 = "20260905_100000_execlog2"
    runlog.log_event(rid2, "run_result", status="needs_input", ok=True, is_paused=True)
    asyncio.run(pipeline.resume_pipeline("tok", approve=True, runner="fake", run_id=rid2))
    kinds = [e.get("kind") for e in _events(rid2)]
    last = next((e for e in reversed(_events(rid2)) if e.get("kind") == "run_result"), {})
    record(kinds[-2:] == ["gate_decision", "run_result"] and last.get("status") == "ok"
           and last.get("after") == "resume",
           "after a resume the newest run_result is the run's real fate", str(kinds))

    # --- run_start says who started it and against which vocabulary -----------
    real_run = pipeline.run_pipeline

    async def fake_run(path, args=None, runner=None):
        return PipelineResult(ok=True, status="ok", runner="fake")

    pipeline.run_pipeline = fake_run
    try:
        # The scheduler's own spec: one step, both values from args.
        spec = {"name": "scheduled-publish", "steps": [
            {"publish.linkedin": {"id": "publish", "in": "none",
                                  "media": {"arg": "media"}, "text": {"arg": "caption"}}}]}
        res = asyncio.run(pipeline.run_pipeline_spec(
            spec, args={"media": "", "caption": "x"}, runner="fake", trigger="scheduled"))
    finally:
        pipeline.run_pipeline = real_run
    start = next((e for e in _events(res.run_id) if e.get("kind") == "run_start"), {})
    record(start.get("trigger") == "scheduled", "run_start records the trigger", str(start.get("trigger")))
    record(isinstance(start.get("vocab_hash"), str) and len(start["vocab_hash"]) == 12
           and bool(start.get("core_version")),
           "and the vocabulary fingerprint and library version",
           f"vocab={start.get('vocab_hash')} core={start.get('core_version')}")
    lobster = Path(start.get("lobster_path", "")).read_text(encoding="utf-8") if start.get("lobster_path") else ""
    record("args.media" in lobster and "args.caption" in lobster,
           "the scheduler's one-step flow compiles with both values wired from args")
    record(runbucket.get(res.run_id, "args.media") == "",
           "an empty media arg is stored, so a text-only post resolves to nothing rather than to a KeyError")

    # --- pipelog reads all of it ------------------------------------------------
    env = {**os.environ, "MORA02_PIPELINE_LOG_DIR": str(LOGS)}
    out = subprocess.run([sys.executable, str(REPO / "scripts" / "pipelog.py"), "--json", "list"],
                         capture_output=True, text=True, env=env)
    rows = {r["run_id"]: r for r in json.loads(out.stdout or "[]")} if out.returncode == 0 else {}
    record(rows.get(res.run_id, {}).get("trigger") == "scheduled" and rows.get(res.run_id, {}).get("status") == "ok",
           "pipelog list shows trigger and final status", str(rows.get(res.run_id))[:90] or out.stderr[:90])
    record(rows.get(rid2, {}).get("status") == "ok", "and the resumed run's fate, not its pause",
           str(rows.get(rid2, {}).get("status")))
    record(rows.get(rid, {}).get("archived") is True, "and that a run was archived")
    show = subprocess.run([sys.executable, str(REPO / "scripts" / "pipelog.py"), "show", rid],
                          capture_output=True, text=True, env=env)
    record(show.returncode == 0 and "bytes" in show.stdout and "run_archived" in show.stdout,
           "pipelog show renders file facts and the archive line", show.stdout.splitlines()[-1][:70] if show.stdout else show.stderr[:90])

    width = max(len(s) for _, s, _ in results)
    failed = 0
    for verdict, subject, detail in results:
        failed += verdict == "FAIL"
        print(f"[ {verdict:^4} ] {subject.ljust(width)}  {detail}")
    print(f"\n{len(results) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main_())
