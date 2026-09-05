#!/usr/bin/env python3
"""The three MCP tools a flow author works with, offline.

flow_ops answers "which step fits here", flow_check answers "is this draft
right yet", flow_save writes into this installation's library and nowhere else.
Each is checked the way a model uses it - through the MCP call, with the
arguments a model sends - and the HTTP save route is checked to give the same
answers, because both doors go through one library function.

    bash tests/agents/run-all.sh
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "lib" / "mora02_core" / "src"))
sys.path.insert(0, str(REPO / "apps" / "script-runner" / "app"))

TMP = Path(tempfile.mkdtemp(prefix="flow-author-"))
LOCAL = TMP / "local"
SHIPPED = TMP / "shipped"
SHIPPED.mkdir()
(SHIPPED / "shipped-demo.json").write_text(json.dumps({"name": "shipped-demo", "steps": []}))
os.environ["MORA02_PIPELINE_SPECS_LOCAL_DIR"] = str(LOCAL)
os.environ["MORA02_PIPELINE_SPECS_DIR"] = str(SHIPPED)
os.environ["MORA02_SCRIPT_RUNNER_DATA"] = str(TMP / "data")

import mcp_tools as M  # noqa: E402
import pipelines  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from mora02_core.pipeline import vocab  # noqa: E402

results: list[tuple[str, str, str]] = []


def record(ok: bool, subject: str, detail: str = "") -> None:
    results.append(("ok" if ok else "FAIL", subject, detail))


def call(name: str, args: dict) -> dict:
    return asyncio.run(M._call(name, args))


GOOD = {"name": "t", "description": "probe", "steps": [
    {"llm.image_prompt": {"id": "prompt", "subject": {"arg": "subject", "default": "x"}}},
    {"image.generate": {"id": "picture", "flow": "photo"}},
    {"review": "ok?"},
    {"clip.generate": {"id": "clip", "resolution": "720p"}},
]}


def main() -> int:
    M.begin_turn({}, session="agent:flow-author:probe")

    # --- flow_ops: the vocabulary a model can hold -----------------------------
    out = call("flow_ops", {})
    ops = {o["op"]: o for o in out.get("ops", [])}
    wired = vocab.wired_op_names()
    record(set(ops) == wired, "flow_ops lists exactly the runnable ops", f"{len(ops)} of {len(wired)}")
    sample = ops.get("image.generate", {})
    record(all(k in sample for k in ("does", "in", "out", "cost", "effect")),
           "each entry says what it does, what goes in and out, and what it costs", str(list(sample))[:80])
    flow_param = next((p for p in sample.get("needs", []) + sample.get("may", []) if p["name"] == "flow"), None)
    record(bool(flow_param and flow_param.get("choices")), "a parameter with choices lists them",
           str(flow_param)[:80])
    record(json.dumps(out) and len(json.dumps(out)) < 20000,
           "the whole answer stays under ~5k tokens", f"{len(json.dumps(out))} chars")
    record(any(p["step"] == "review" for p in out.get("pauses", [])) and "wiring" in out,
           "the two pauses and the wiring rules travel with the list")
    after = call("flow_ops", {"after": "image.generate"})
    names = {o["op"] for o in after["ops"]}
    text_only = {o.name for o in vocab.all_ops() if o.input_type == "text" and o.consumes != "none"}
    record(names and not (names & text_only) and "clip.generate" in names,
           "after a picture, no text-reading op is offered and the clip op is",
           f"{len(names)} candidates")
    record(bool(call("flow_ops", {"after": "no.such"}).get("note")),
           "an unknown `after` says so instead of answering with nothing")

    # --- flow_check: every problem at once, in words ---------------------------
    bad = {"name": "t", "steps": [
        {"llm.image_prompt": {"id": "prompt", "subjekt": "x"}},          # misspelled param
        {"image.generate": {"id": "picture", "flow": "phot"}},           # bad choice
        {"clip.generate": {"id": "clip", "in": "later"}},                # forward reference
        {"image.generate": {"id": "later", "flow": "photo"}},
    ]}
    out = call("flow_check", {"spec": bad})
    probs = " | ".join(out.get("problems", []))
    record(out.get("ok") is False and len(out["problems"]) >= 3,
           "three different mistakes come back together, not one per round",
           f"{len(out.get('problems', []))} problems")
    record("subjekt" in probs and "phot" in probs and "later" in probs,
           "and each names the thing that is wrong", probs[:120])
    record(bool(out.get("hint")), "with a hint that points back to flow_ops")
    record(call("flow_check", {"spec": GOOD}).get("ok") is True, "a right draft is ok")
    record(call("flow_check", {"spec": "nonsense"}).get("ok") is False, "a spec that is not an object is refused")
    planned = next((o.name for o in vocab.all_ops() if o.status != "wired"), None)
    if planned:
        out = call("flow_check", {"spec": {"name": "t", "steps": [{planned: {"id": "p"}}]}})
        record(out.get("ok") is True and any(planned in w for w in out.get("warnings", [])),
               "a planned op is a warning, not a refusal - authoring ahead of a handler is allowed",
               planned)

    # --- flow_save: into the local library, checked, once ----------------------
    record("error" in call("flow_save", {"name": "Bad Name", "spec": GOOD}), "a name that cannot be a file is refused")
    record("error" in call("flow_save", {"name": "t", "spec": bad}) and not (LOCAL / "t.json").exists(),
           "a draft the check refuses is not written")
    out = call("flow_save", {"name": "probe-flow", "spec": GOOD})
    record(out.get("ok") and (LOCAL / "probe-flow.json").is_file() and not (SHIPPED / "probe-flow.json").exists(),
           "a good draft lands in the LOCAL library, never in the shipped one", str(out.get("file")))
    record("Nothing was started" in (out.get("note") or ""), "and the answer says nothing was started")
    saved = json.loads((LOCAL / "probe-flow.json").read_text())
    clip = next(s for s in saved["steps"] if "clip.generate" in s)["clip.generate"]
    record(clip.get("in") == "review_send", "the implicit wiring is written down on save", str(clip.get("in")))
    again = call("flow_save", {"name": "probe-flow", "spec": GOOD})
    record("error" in again and "overwrite" in (again.get("hint") or ""), "a taken name is refused with the way out named")
    record(call("flow_save", {"name": "probe-flow", "spec": GOOD, "overwrite": True}).get("replaced") is True,
           "and replaced only when asked")
    out = call("flow_save", {"name": "shipped-demo", "spec": GOOD})
    record("error" in out, "a shipped flow's name counts as taken", (out.get("error") or "")[:60])

    # --- the HTTP door gives the same answers ----------------------------------
    app = FastAPI()
    app.include_router(pipelines.router)
    with TestClient(app) as client:
        r = client.post("/pipeline/flow/Bad%20Name", json=GOOD)
        record(r.status_code == 400, "HTTP: a bad name is 400", str(r.status_code))
        r = client.post("/pipeline/flow/http-probe", json=bad)
        record(r.status_code == 422 and "subjekt" in r.text, "HTTP: a refused draft is 422 with the problems", str(r.status_code))
        r = client.post("/pipeline/flow/http-probe", json=GOOD)
        record(r.status_code == 200 and r.json().get("source") == "local", "HTTP: a good draft saves locally", str(r.status_code))
        r = client.post("/pipeline/flow/http-probe", json=GOOD)
        record(r.status_code == 409, "HTTP: saving again without overwrite is 409", str(r.status_code))
        r = client.delete("/pipeline/flow/shipped-demo")
        record(r.status_code == 403, "HTTP: a shipped flow cannot be deleted", str(r.status_code))

    M.end_turn()
    width = max(len(s) for _, s, _ in results)
    failed = 0
    for verdict, subject, detail in results:
        failed += verdict == "FAIL"
        print(f"[ {verdict:^4} ] {subject.ljust(width)}  {detail}")
    print(f"\n{len(results) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
