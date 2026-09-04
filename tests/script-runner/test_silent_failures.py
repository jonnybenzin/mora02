#!/usr/bin/env python3
"""Does a failure look like a failure?

Review run 3 (2026-09-04) found four places that reported a green result for
something that had not happened. None of them raised, logged an error a person
sees, or coloured a step red — which is what makes this class expensive: the
run looks finished, and the wrong conclusion is drawn downstream.

What this suite pins down:

  * a database call that was REFUSED is distinct from one that found nothing.
    Both used to be `None`, so `db.insert` reported ok with `"null"` for a row
    that was never created, and `db.query` answered an empty list for a
    database that was unreachable — which the scheduled-publish loop reads as
    "nothing is due"
  * a cloud call's cost counts the cache reads it was billed for
  * `/pipeline/vocab-stats?window_days=N` applies N to every number it reports,
    not only to the spend
  * a background resume that fails writes its fate into the run log, because
    the caller was told "resuming" before it was tried and the inbox item is
    already gone

Offline and free: no database, no model, no gateway. The HTTP layer is stubbed.

Usage:
    PYTHONPATH=lib/mora02_core/src:apps/script-runner/app \\
        python3 tests/script-runner/test_silent_failures.py
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
import types
from datetime import datetime, timedelta, timezone
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

DATA = Path(tempfile.mkdtemp(prefix="sr-silent-"))
LOGS = DATA / "logs"
LOGS.mkdir(parents=True, exist_ok=True)
os.environ["MORA02_SCRIPT_RUNNER_DATA"] = str(DATA)
os.environ["MORA02_PIPELINE_LOG_DIR"] = str(LOGS)

import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from mora02_core import pricing  # noqa: E402
from mora02_core.db import api as db_api  # noqa: E402
from mora02_core.pipeline import runlog  # noqa: E402

results: list[tuple[str, str, str]] = []


def record(ok: bool, subject: str, detail: str = "") -> None:
    results.append(("PASS" if ok else "FAIL", subject, detail))
    print(f"[{'  ok  ' if ok else ' FAIL '}] {subject}{(': ' + detail) if detail else ''}")


class FakeResponse:
    def __init__(self, status_code: int, payload=None, text: str = ""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text or json.dumps(self._payload)

    def json(self):
        return self._payload


class FakeClient:
    """Stands in for httpx.AsyncClient: every verb answers the same canned
    response, so a refusal can be produced without a database."""

    def __init__(self, response: FakeResponse):
        self._r = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, *a, **k):
        return self._r

    async def post(self, *a, **k):
        return self._r

    async def patch(self, *a, **k):
        return self._r

    async def delete(self, *a, **k):
        return self._r


def with_db_response(resp: FakeResponse):
    real = db_api.httpx.AsyncClient
    db_api.httpx.AsyncClient = lambda *a, **k: FakeClient(resp)
    return real


def main_() -> int:
    # --- a refusal is not an empty result ----------------------------------
    real = with_db_response(FakeResponse(400, {}, "field 'Titel' is unknown"))
    try:
        for name, call in [
            ("db.insert", db_api.insert("sb_assets", {"a": 1})),
            ("db.query", db_api.query("sb_assets")),
            ("db.update", db_api.update("sb_assets", 1, {"a": 1})),
            ("db.delete", db_api.delete("sb_assets", 1)),
            ("db.list_fields", db_api.list_fields("sb_assets")),
        ]:
            try:
                asyncio.run(call)
            except db_api.DbError as e:
                record(True, f"a refused {name} raises rather than answering", str(e)[:56])
            else:
                record(False, f"a refused {name} raises rather than answering", "answered")
    finally:
        db_api.httpx.AsyncClient = real

    # a row that is simply not there stays a None, not an error
    real = with_db_response(FakeResponse(404, {}, "not found"))
    try:
        record(asyncio.run(db_api.get("sb_assets", 7)) is None,
               "a row that is not there is still None, not a failure")
        record(asyncio.run(db_api.delete("sb_assets", 7)) is False,
               "deleting a row that is not there is False, not a failure")
    finally:
        db_api.httpx.AsyncClient = real

    # and the step handler turns "not there" into a failed step, not ok+null
    real = with_db_response(FakeResponse(404, {}, "not found"))
    try:
        try:
            asyncio.run(main._step_db_get([], {"table": "sb_assets", "row_id": "7"}))
        except ValueError as e:
            record("no row" in str(e), "db.get on a missing row is a failed STEP", str(e)[:50])
        else:
            record(False, "db.get on a missing row is a failed STEP", "returned ok")
    finally:
        db_api.httpx.AsyncClient = real

    real = with_db_response(FakeResponse(200, {"id": 5, "Name": "x"}))
    try:
        out = asyncio.run(main._step_db_get([], {"table": "sb_assets", "row_id": "5"}))
        record(out["ok"] and json.loads(out["out"])["id"] == 5,
               "a row that IS there still comes back", out["out"][:40])
    finally:
        db_api.httpx.AsyncClient = real

    # --- the cost of a cached call -----------------------------------------
    plain = pricing.usd_last_call("claude-sonnet-4-6", tokens_in=1, tokens_out=3031)
    cached = pricing.usd_last_call("claude-sonnet-4-6", tokens_in=1, tokens_out=3031,
                                   tokens_cache_read=50000)
    record(cached > plain, "cache reads are billed, so they raise the reported cost",
           f"{plain:.6f} -> {cached:.6f} USD")
    expected = (1 / 1e6) * 3.0 + (50000 / 1e6) * 3.0 * pricing.CACHE_READ_SHARE + (3031 / 1e6) * 15.0
    record(abs(cached - expected) < 1e-9, "and at the documented share of the input rate")
    src = (ROOT / "lib/mora02_core/src/mora02_core/llm/claude_api.py").read_text()
    record("usd_last_call" in src and "cost_input_per_1m" not in src,
           "the cloud client no longer carries its own copy of the formula")

    # --- the stats window applies to every number --------------------------
    now = datetime.now(timezone.utc)
    old = (now - timedelta(days=90)).isoformat()
    fresh = now.isoformat()
    rid = runlog.new_run_id()
    with open(LOGS / f"{rid}.jsonl", "w", encoding="utf-8") as fh:
        for _ in range(5):
            fh.write(json.dumps({"kind": "step", "op": "image.generate", "status": "ok",
                                 "ts": old, "duration_ms": 100, "cost_usd": 1.0}) + "\n")
        fh.write(json.dumps({"kind": "step", "op": "image.generate", "status": "ok",
                             "ts": fresh, "duration_ms": 100, "cost_usd": 2.0}) + "\n")
    client = TestClient(main.app)
    r = client.get("/pipeline/vocab-stats?window_days=1")
    ops = r.json().get("ops", {})
    got = ops.get("image.generate", {})
    record(got.get("runs") == 1,
           "with window_days=1 only the run inside the window is counted",
           f"runs={got.get('runs')} (six in the log, five of them 90 days old)")
    main._VOCAB_STATS_CACHE.update(signature=None, payload=None)
    r = client.get("/pipeline/vocab-stats?window_days=365")
    got = r.json().get("ops", {}).get("image.generate", {})
    record(got.get("runs") == 6, "with a wide window all six are counted",
           f"runs={got.get('runs')}")

    # --- a background resume that fails says so in the run log -------------
    rid2 = runlog.new_run_id()

    async def boom(*a, **k):
        raise RuntimeError("lobster resume produced no JSON envelope")

    real_resume = main.resume_pipeline
    main.resume_pipeline = boom
    try:
        req = main.PipelineResumeRequest(token="t", run_id=rid2, background=True)
        asyncio.run(main._bg_resume_and_refile(req))
    finally:
        main.resume_pipeline = real_resume
    events = runlog.read_events(rid2)
    fated = [e for e in events if e.get("kind") == "run_result"]
    record(bool(fated) and fated[0].get("ok") is False,
           "a failed background resume is written into the run log",
           (fated[0].get("error", "") if fated else "nothing was written")[:56])

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
