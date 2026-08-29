#!/usr/bin/env python3
"""Phase 7 of the test plan: every op once, in a chain, staggered by what it costs.

The other suites test the machinery around the vocabulary - transport, wiring,
gates, re-runs. This one asks the plainest question about each verb: put in a
chain behind a step that feeds it, does it do its job and hand on a value of the
type it promised?

In a chain, not alone: an op called by itself never has to accept what the step
before it produced, and that handover is where the defects of 26 August lived.

Cost is a first-class concern here, so nothing runs unless it is asked for:

    --tier 1   free, seconds        llm.*, web.*, db reads, source.file
    --tier 2   local GPU minutes    image ops, text.overlay, pixeltext, gif
    --tier 3   real money           image.edit, cloud.complete, cloud.vision
    --tier 4   long and partly paid video, music, tts, clip
    --tier 5   VISIBLE OUTSIDE      notify (Signal), publish.linkedin

Tier 5 sends real messages and publishes publicly; it never runs without being
named explicitly, and publish.linkedin additionally requires --i-mean-it.

Usage:
    python3 tests/pipeline/test_vocabulary.py --tier 1
    python3 tests/pipeline/test_vocabulary.py --tier 1,2,3

Environment: SCRIPT_RUNNER_URL, MORA02_PIPELINE_LOG_DIR, MORA02_TEST_TABLE
(a Baserow table id used for db reads; defaults to the feedback table).
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
TABLE = os.environ.get("MORA02_TEST_TABLE", "576")
SEED_URL = "http://127.0.0.1:8096/health"

TEXT_SEED = {"web.fetch": {"id": "seed", "in": "none", "url": SEED_URL}}
PIC_SEED = {"source.file": {"id": "pic", "in": "none", "store": "comfyui", "pick": "latest"}}

results: list[tuple[str, str, str]] = []


def record(verdict: str, subject: str, detail: str) -> None:
    results.append((verdict, subject, detail))
    # Print immediately, not only in the summary: a long GPU tier that is killed
    # halfway must still have reported everything it got through.
    print(f"{verdict:4}  {subject}  {detail}", flush=True)


def post(path: str, payload: dict, timeout: int = 900) -> dict:
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


def step_event(run_id: str, step_id: str) -> dict | None:
    path = LOG_DIR / f"{run_id}.jsonl"
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("kind") == "step" and e.get("step_id") == step_id:
            return e
    return None


MEDIA_TYPES = {"image", "video", "audio"}


ONLY: set[str] = set()


def check(op: str, tier: int, steps: list, out_type: str, timeout: int = 900) -> None:
    """Run a chain ending in `op` and judge the op's own step event."""
    if ONLY and op not in ONLY:
        return
    started = time.monotonic()
    res = post("/pipeline/run-spec",
               {"spec": {"name": f"vocab-{op.replace('.', '-')}-{int(time.time())}",
                         "steps": steps}}, timeout=timeout)
    took = round(time.monotonic() - started, 1)
    if res.get("http_status"):
        record("FAIL", f"[{tier}] {op}", f"refused: {res.get('detail') or res}")
        return
    run_id = res.get("run_id")
    ev = step_event(run_id, "probe") if run_id else None
    if ev is None:
        record("FAIL", f"[{tier}] {op}",
               f"no step event (run {run_id}, status {res.get('status')}) after {took}s")
        return
    if ev.get("status") != "ok":
        record("FAIL", f"[{tier}] {op}", f"failed: {str(ev.get('error'))[:100]}")
        return
    out = ev.get("out") or ""
    if out_type in MEDIA_TYPES:
        ok = isinstance(out, str) and out.startswith("asset://")
        detail = f"{took}s -> {out[:56]}" if ok else f"expected an asset ref, got {out[:60]!r}"
    else:
        ok = isinstance(out, str) and out.strip() != ""
        detail = f"{took}s -> {out[:56]!r}" if ok else "empty output"
    record("PASS" if ok else "FAIL", f"[{tier}] {op}", detail)


def tier1() -> None:
    t = 1
    check("llm.complete", t, [TEXT_SEED, {"llm.complete": {
        "id": "probe", "in": "seed", "prompt": "Antworte mit einem Satz über Leuchttürme."}}], "text")
    check("llm.summarize", t, [TEXT_SEED, {"llm.summarize": {
        "id": "probe", "in": "seed", "max_tokens": 60}}], "text")
    check("llm.classify", t, [TEXT_SEED, {"llm.classify": {
        "id": "probe", "in": "seed", "labels": "status,rezept,gedicht"}}], "text")
    check("llm.extract", t, [TEXT_SEED, {"llm.extract": {
        "id": "probe", "in": "seed", "fields": "status,version"}}], "text")
    check("llm.translate", t, [TEXT_SEED, {"llm.translate": {
        "id": "probe", "in": "seed", "to": "German"}}], "text")
    check("llm.image_prompt", t, [TEXT_SEED, {"llm.image_prompt": {
        "id": "probe", "in": "none", "subject": "ein Leuchtturm im Sturm"}}], "text")
    check("web.fetch", t, [TEXT_SEED, {"web.fetch": {
        "id": "probe", "in": "none", "url": SEED_URL}}], "text")
    check("web.search", t, [TEXT_SEED, {"web.search": {
        "id": "probe", "in": "none", "query": "leuchtturm"}}], "text")
    check("stock.search", t, [TEXT_SEED, {"stock.search": {
        "id": "probe", "in": "none", "query": "lighthouse", "count": 2}}], "text")
    check("db.query", t, [TEXT_SEED, {"db.query": {
        "id": "probe", "in": "none", "table": TABLE, "size": 2}}], "text")
    check("db.list_fields", t, [TEXT_SEED, {"db.list_fields": {
        "id": "probe", "in": "none", "table": TABLE}}], "text")
    check("source.file", t, [TEXT_SEED, {"source.file": {
        "id": "probe", "in": "none", "store": "comfyui", "pick": "latest"}}], "image")


def tier2() -> None:
    t = 2
    check("image.generate", t, [TEXT_SEED, {"image.generate": {
        "id": "probe", "in": "none", "prompt": "a small red lighthouse, plain background",
        "flow": "sd15", "format": "square"}}], "image", timeout=900)
    for op in ("image.cutout", "image.erase", "image.upscale", "image.expand",
               "image.facefix"):
        check(op, t, [PIC_SEED, {op: {"id": "probe", "in": "pic"}}], "image", timeout=900)
    check("text.overlay", t, [TEXT_SEED, {"text.overlay": {
        "id": "probe", "in": "seed", "text": "TESTLAUF"}}], "image", timeout=600)
    check("pixeltext.render", t, [TEXT_SEED, {"pixeltext.render": {
        "id": "probe", "in": "none", "text": "TEST"}}], "video", timeout=900)
    check("gif.create", t, [PIC_SEED, {"gif.create": {
        "id": "probe", "in": ["pic"]}}], "video", timeout=600)


def tier3() -> None:
    t = 3
    check("cloud.complete", t, [TEXT_SEED, {"cloud.complete": {
        "id": "probe", "in": "seed", "prompt": "Antworte mit einem Satz.",
        "max_tokens": 100}}], "text")
    # The vocabulary calls this one's parameter "query" while cloud.complete says
    # "prompt" - worth knowing, and the reason a spec is validated against the
    # vocabulary rather than against habit.
    check("cloud.vision", t, [PIC_SEED, {"cloud.vision": {
        "id": "probe", "in": "pic", "query": "Was ist auf dem Bild? Ein Satz."}}], "text")
    check("image.edit", t, [PIC_SEED, {"image.edit": {
        "id": "probe", "in": "pic", "prompt": "make the sky slightly bluer"}}],
        "image", timeout=900)


def tier4() -> None:
    t = 4
    check("tts.speak", t, [TEXT_SEED, {"tts.speak": {
        "id": "probe", "in": "none", "text": "This is a pipeline test.",
        "language": "en"}}], "audio", timeout=900)
    check("music.generate", t, [TEXT_SEED, {"music.generate": {
        "id": "probe", "in": "none", "prompt": "calm ambient", "duration": 10}}],
        "audio", timeout=1200)
    check("video.generate", t, [PIC_SEED, {"video.generate": {
        "id": "probe", "in": "pic", "mode": "i2v", "prompt": "slow gentle motion"}}],
        "video", timeout=1800)
    check("video.last_frame", t, [PIC_SEED,
        {"video.generate": {"id": "vid", "in": "pic", "mode": "i2v",
                            "prompt": "slow gentle motion"}},
        {"video.last_frame": {"id": "probe", "in": "vid"}}], "image", timeout=1800)
    check("clip.generate", t, [PIC_SEED, {"clip.generate": {
        "id": "probe", "in": ["pic"], "resolution": "720p", "durations": "2"}}],
        "video", timeout=900)


def tier5(allow_publish: bool) -> None:
    t = 5
    # No explicit target: the op falls back to MORA02_SIGNAL_TARGET inside the
    # container, which is where the number lives and how a real flow reaches a
    # human. Reading that variable from THIS shell would find nothing and report
    # a skip that looks like a result.
    check("notify", t, [TEXT_SEED, {"notify": {
        "id": "probe", "in": "seed",
        "message": "Pipeline-Testlauf (Text) — bitte ignorieren."}}], "text")
    check("notify.image", t, [PIC_SEED, {"notify.image": {
        "id": "probe", "in": "pic",
        "message": "Pipeline-Testlauf (Bild) — bitte ignorieren."}}], "image")
    if not allow_publish:
        record("n/a", "[5] publish.linkedin",
               "posts publicly - needs --i-mean-it and a word from the user")
        return
    check("publish.linkedin", t, [TEXT_SEED, {"publish.linkedin": {
        "id": "probe", "in": "none",
        "text": "Test post from the mora02 pipeline suite.",
        "visibility": "CONNECTIONS"}}], "text")


NOT_RUN = {
    "llm.switch": "switches the LLM profile and restarts llama-server for minutes - "
                  "disruptive, run it deliberately",
    "db.insert": "writes a row; needs a scratch table, not a live one",
    "db.update": "writes a row; needs a scratch table, not a live one",
    "db.delete": "deletes a row; needs a scratch table, not a live one",
    "db.get": "needs a known row id; pair it with a scratch table",
    "stock.download": "cannot be reached from a chain until the field-pick op exists "
                      "(it takes source and image_url as params, stock.search emits a list)",
}


def main() -> int:
    tiers = set()
    for i, a in enumerate(sys.argv):
        if a == "--tier" and i + 1 < len(sys.argv):
            tiers = {int(x) for x in sys.argv[i + 1].split(",") if x.strip().isdigit()}
        if a == "--only" and i + 1 < len(sys.argv):
            ONLY.update(x.strip() for x in sys.argv[i + 1].split(",") if x.strip())
    if not tiers:
        print("say which tiers to run, e.g. --tier 1  (see the docstring for costs)")
        return 2

    if 1 in tiers:
        tier1()
    if 2 in tiers:
        tier2()
    if 3 in tiers:
        tier3()
    if 4 in tiers:
        tier4()
    if 5 in tiers:
        tier5("--i-mean-it" in sys.argv)
    if not ONLY:
        for op, why in NOT_RUN.items():
            record("n/a", f"[-] {op}", why)

    width = max(len(s) for _, s, _ in results)
    failed = sum(1 for v, _, _ in results if v == "FAIL")
    na = sum(1 for v, _, _ in results if v == "n/a")
    print()
    for verdict, subject, detail in results:
        print(f"{verdict:4}  {subject.ljust(width)}  {detail}")
    print(f"\n{len(results) - failed - na} passed, {failed} failed, {na} not run")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
