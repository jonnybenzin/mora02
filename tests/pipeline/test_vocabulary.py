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
    --tier 6   TAKES THE MODEL DOWN llm.switch (a minute per switch, and back)

Tier 5 sends real messages and publishes publicly; it never runs without being
named explicitly, and publish.linkedin additionally requires --i-mean-it.

Usage:
    python3 tests/pipeline/test_vocabulary.py --tier 1
    python3 tests/pipeline/test_vocabulary.py --tier 1,2,3

Environment: SCRIPT_RUNNER_URL, MORA02_PIPELINE_LOG_DIR, MORA02_TEST_TABLE
(a SCRATCH Baserow table — the db ops create, change and delete a row in it, so
never point it at a live table. Unset means the db ops report themselves as not
run, with the reason.)
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
# A scratch table for the db ops. Machine-specific, so it comes from the
# environment rather than from this file: `export MORA02_TEST_TABLE=<id>`. The
# writing ops need a table nobody relies on - they create, change and delete a
# row - so pointing this at a live table is a bad idea. Unset means the db ops
# report themselves as not run, with the reason.
TABLE = os.environ.get("MORA02_TEST_TABLE", "")
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


def step_json(op_and_query: str, data: dict | None = None) -> dict | None:
    """Call one step endpoint directly and read its JSON answer back.

    Used by the db cycle, which cannot be one chain: each op needs the row id out
    of the previous one's JSON, and picking a field out of JSON is the very op
    that does not exist yet. Returns None when the step refuses - which is the
    expected answer after a delete.
    """
    body = json.dumps(data).encode("utf-8") if data is not None else b""
    req = urllib.request.Request(f"{RUNNER}/pipeline/step/{op_and_query}&fmt=out",
                                 data=body, method="POST",
                                 headers={"Content-Type": "text/plain; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            text = r.read().decode("utf-8", "replace")
    except Exception:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


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


def audit_facts() -> None:
    """Every wired op must carry what the VOKABULAR table cannot measure.

    Duration, spend and last-use come from the run log. Where an op runs, what
    it is built on, whether money moves and whether it can be undone cannot be
    derived from anything - they have to be stated. An op added without them
    leaves a hole in the table, and a table with holes stops being consulted,
    which is a slower and more expensive failure than a red test.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib/mora02_core/src"))
    try:
        from mora02_core.pipeline import vocab
    except ImportError as e:
        record("FAIL", "vocabulary facts", f"cannot import the vocabulary: {e}")
        return

    gaps = []
    for op in vocab.all_ops():
        if op.status != "wired":
            continue
        missing = [f for f in ("runs_on", "service") if not getattr(op, f, "")]
        if op.cost in ("paid", "mixed") and not op.cost_note:
            missing.append("cost_note (it costs money, so say what is billed)")
        if missing:
            gaps.append(f"{op.name}: {', '.join(missing)}")
    if gaps:
        record("FAIL", "every wired op states its facts",
               f"{len(gaps)} incomplete: {'; '.join(gaps[:3])}")
    else:
        record("PASS", "every wired op states its facts",
               f"{len(vocab.wired_op_names())} ops carry runs_on, service and a price note")


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
    # The seed is the health JSON, so scripts.0 is a known value: "gifer".
    check("data.pick", t, [TEXT_SEED, {"data.pick": {
        "id": "probe", "in": "seed", "path": "scripts.0"}}], "text")
    # The chain that was impossible until data.pick existed: a search emits a list
    # of hits, the download wants one url out of it. Three steps, no hand-copying.
    check("stock.download", t, [
        {"stock.search": {"id": "hits", "in": "none", "source": "pexels",
                          "query": "lighthouse", "count": 3}},
        {"data.pick": {"id": "url", "in": "hits", "path": "results.0.url"}},
        {"stock.download": {"id": "probe", "in": "none", "source": "pexels",
                            "image_url": {"from": "url"}}}], "image")
    if not TABLE:
        record("n/a", "[1] db.* (alle)",
               "set MORA02_TEST_TABLE to a scratch table id to include them")
        return
    check("db.query", t, [TEXT_SEED, {"db.query": {
        "id": "probe", "in": "none", "table": TABLE, "size": 2}}], "text")
    check("db.list_fields", t, [TEXT_SEED, {"db.list_fields": {
        "id": "probe", "in": "none", "table": TABLE}}], "text")
    db_write_cycle()


def db_write_cycle() -> None:
    """create a row, read it, change it, delete it - each op checking the last.

    Not one chain, deliberately. db.insert returns the new row as JSON and
    db.get needs the id out of it, which is precisely the field-pick op that
    does not exist yet - the same gap that keeps stock.download unreachable
    from a chain. So the ids travel through this function instead, and the
    limitation is visible here rather than hidden behind a helper.

    The cycle cleans up after itself because deleting IS one of the ops under
    test. If it breaks in the middle, the row it leaves behind is named so it
    can be found by eye.
    """
    t = 1
    marker = f"PIPELINE-TESTLAUF {int(time.time())}"
    row = step_json(f"db.insert?table={TABLE}", {"Name": marker, "Notes": "angelegt"})
    row_id = (row or {}).get("id")
    if not row_id:
        record("FAIL", "[1] db.insert", f"no row id came back: {str(row)[:90]}")
        return
    record("PASS", "[1] db.insert", f"row {row_id} created")

    got = step_json(f"db.get?table={TABLE}&row_id={row_id}")
    ok = (got or {}).get("Name") == marker
    record("PASS" if ok else "FAIL", "[1] db.get",
           f"read back {marker!r}" if ok else f"read back something else: {str(got)[:80]}")

    changed = step_json(f"db.update?table={TABLE}&row_id={row_id}", {"Notes": "geaendert"})
    ok = (changed or {}).get("Notes") == "geaendert"
    record("PASS" if ok else "FAIL", "[1] db.update",
           "the change took" if ok else f"unchanged: {str(changed)[:80]}")

    step_json(f"db.delete?table={TABLE}&row_id={row_id}")
    gone = step_json(f"db.get?table={TABLE}&row_id={row_id}")
    record("PASS" if gone is None else "FAIL", "[1] db.delete",
           "the row is gone" if gone is None
           else f"still readable after delete - row {row_id} left behind")
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


def tier6() -> None:
    """llm.switch - its own tier because it takes the local model down and up.

    Roughly a minute per switch, during which no llm.* op can answer. It is run
    deliberately, never as part of a sweep, and it puts the profile back where it
    found it - a test that leaves the machine on a different model has broken
    something even if every assertion passed.
    """
    state = Path(os.environ.get("MORA02_LLM_SWITCH_STATE",
                                "/opt/mora02/llm-switch/current.json"))
    if not state.is_file():
        record("n/a", "[6] llm.switch", f"no profile state at {state}")
        return
    before = json.loads(state.read_text()).get("profile")
    other = "qwen3-8b" if before != "qwen3-8b" else "qwen3-14b"

    check("llm.switch", 6, [TEXT_SEED, {"llm.switch": {
        "id": "probe", "in": "seed", "profile": other}}], "text", timeout=400)

    now = json.loads(state.read_text()).get("profile")
    record("PASS" if now == other else "FAIL", "[6] llm.switch · profile changed",
           f"{before} -> {now}")

    # Back where we found it, and checked - not assumed.
    step_json(f"llm.switch?profile={before}")
    restored = json.loads(state.read_text()).get("profile")
    record("PASS" if restored == before else "FAIL", "[6] llm.switch · profile restored",
           f"back on {restored}" if restored == before
           else f"LEFT ON {restored}, expected {before} - switch it back by hand")


NOT_RUN: dict[str, str] = {}


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

    audit_facts()   # needs no services, so it runs whatever tier was asked for
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
    if 6 in tiers:
        tier6()
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
