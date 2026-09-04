#!/usr/bin/env python3
"""Does the service still answer while it is busy?

script-runner runs on a single uvicorn worker. That one event loop serves the
Pilot's chat and its polling, the MCP surface during an agent turn, and every
pipeline step of a run in flight. Review run 3 (2026-09-04) found nine places
doing synchronous disk, subprocess and HTTP work directly on it — the worst
being `/tts/generate`, whose library call uses synchronous httpx with a timeout
of up to 180 seconds. The pipeline's own step handlers already did this
correctly, one screen away, which is what made it a defect rather than a
decision.

This suite does not read the code and assert that a wrapper is present — that
would pass just as happily if the wrapper were around the wrong thing. It makes
a call block for real and checks that a second request is still served while it
does.

Offline and free: the blocking work is a stub that sleeps.

Usage:
    PYTHONPATH=lib/mora02_core/src:apps/script-runner/app \\
        python3 tests/script-runner/test_loop_free.py
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
import threading
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib" / "mora02_core" / "src"))
sys.path.insert(0, str(ROOT / "apps" / "script-runner" / "app"))

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

DATA = Path(tempfile.mkdtemp(prefix="sr-loop-"))
os.environ["MORA02_SCRIPT_RUNNER_DATA"] = str(DATA)
os.environ["MORA02_PIPELINE_LOG_DIR"] = str(DATA / "logs")

import main  # noqa: E402
import speech  # noqa: E402
import httpx  # noqa: E402

results: list[tuple[str, str, str]] = []
BLOCK_S = 0.6


class _Asset:
    """What tts_lib.generate hands back: the handler reads .metadata off it."""
    metadata = {"url": "http://x/x.wav", "filename": "x.wav", "voice": "v",
                "engine": "stub", "language": "de", "text_length": 5}


def record(ok: bool, subject: str, detail: str = "") -> None:
    results.append(("PASS" if ok else "FAIL", subject, detail))
    print(f"[{'  ok  ' if ok else ' FAIL '}] {subject}{(': ' + detail) if detail else ''}")


async def _probe_while(busy_coro, label: str) -> tuple[bool, float]:
    """Start `busy_coro`, then time a health check taken while it runs."""
    task = asyncio.create_task(busy_coro)
    await asyncio.sleep(0.05)  # let it get into the blocking part
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        t0 = time.monotonic()
        r = await c.get("/health")
        waited = time.monotonic() - t0
    await task
    return r.status_code == 200, waited


def main_() -> int:
    calls: list[str] = []

    def slow_tts(*a, **k):
        calls.append("tts")
        time.sleep(BLOCK_S)          # a real, thread-blocking sleep
        return _Asset()

    real = speech.tts_lib.generate
    speech.tts_lib.generate = slow_tts
    try:
        async def busy():
            transport = httpx.ASGITransport(app=main.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://t",
                                         timeout=30) as c:
                await c.post("/tts/generate", json={"text": "hallo"})

        served, waited = asyncio.run(_probe_while(busy(), "tts"))
    finally:
        speech.tts_lib.generate = real

    record(bool(calls), "the blocking call really was reached", f"{len(calls)} call(s)")
    record(served, "the service answers a health check during a speech render")
    record(waited < BLOCK_S / 2,
           "and answers it without waiting for the render to finish",
           f"waited {waited * 1000:.0f} ms of a {BLOCK_S * 1000:.0f} ms render")

    # The same shape for the run log, which the Runs view polls every 3 seconds
    # for as long as a run looks alive.
    (DATA / "logs").mkdir(parents=True, exist_ok=True)
    rid = "20260904_120000_abcdef01"
    (DATA / "logs" / f"{rid}.jsonl").write_text(
        '{"kind": "run_start", "run_id": "%s", "ts": "2026-09-04T12:00:00+00:00"}\n' % rid)
    real_read = main._read_run_events

    def slow_read(run_id):
        time.sleep(BLOCK_S)
        return real_read(run_id)

    main._read_run_events = slow_read
    try:
        async def busy2():
            transport = httpx.ASGITransport(app=main.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://t",
                                         timeout=30) as c:
                await c.get(f"/pipeline/run/{rid}")

        served, waited = asyncio.run(_probe_while(busy2(), "runlog"))
    finally:
        main._read_run_events = real_read

    record(served, "the service answers while a run log is being read")
    record(waited < BLOCK_S / 2,
           "and does not wait for the read",
           f"waited {waited * 1000:.0f} ms of a {BLOCK_S * 1000:.0f} ms read")

    # A thread really is where the work went, not just "somewhere else".
    seen: list[int] = []

    def note_thread(*a, **k):
        seen.append(threading.get_ident())
        return _Asset()

    speech.tts_lib.generate = note_thread
    try:
        async def one():
            transport = httpx.ASGITransport(app=main.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
                await c.post("/tts/generate", json={"text": "x"})
            return threading.get_ident()

        loop_thread = asyncio.run(one())
    finally:
        speech.tts_lib.generate = real
    record(bool(seen) and seen[0] != loop_thread,
           "the work ran on another thread than the loop",
           f"loop={loop_thread} work={seen[0] if seen else '-'}")

    fails = [r for r in results if r[0] == "FAIL"]
    print(f"\n{len(results) - len(fails)} passed, {len(fails)} failed")
    for _, s, d in fails:
        print(f"  FAILED  {s}: {d}")
    return 1 if fails else 0


if __name__ == "__main__":
    try:
        sys.exit(main_())
    finally:
        shutil.rmtree(DATA, ignore_errors=True)
