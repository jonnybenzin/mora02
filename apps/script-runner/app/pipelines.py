"""Pipelines: run, re-run and resume a flow; the flow library; the runs view.

Split out of main.py in September 2026. Relay for the headless HITL pipeline
runtime (ADR-022): script-runner holds the docker socket (ADR-020), so it is
the executor -- it calls mora02_core.pipeline, which runs `docker exec
mora02-openclaw lobster run|resume`. Pilot stays socket-free and drives HITL
through these routes: run a flow, then resume it once a human has decided in
the Pilot inbox. The individual step verbs are in steps.py. Same shape as the
other routers main.py includes.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from mora02_core import assets as asset_refs
from mora02_core.pipeline import (
    PipelineError,
    rerun_pipeline_spec,
    resume_pipeline,
    run_pipeline,
    run_pipeline_spec,
    runlog as pipeline_runlog,
    spec as pipeline_spec,
    vocab as pipeline_vocab,
)
from runtime import _checked_run_id, _FLOW_NAME_RE, _log

router = APIRouter()

class PipelineRunRequest(BaseModel):
    pipeline_path: str            # container path to the .lobster workflow file
    args: Optional[dict] = None   # optional --args-json payload
    runner: Optional[str] = None  # override MORA02_PIPELINE_RUNNER (default lobster)


class PipelineRerunRequest(BaseModel):
    """Re-run only what a change made stale, replaying the rest of an earlier run."""
    source_run_id: str              # the run whose stored outputs get replayed
    changed: list[str]              # compiled step ids the user touched
    overrides: Optional[dict] = None  # {step_id: {param: value}} applied before compiling
    spec: Optional[dict] = None     # a spec that may DIFFER from the one that ran
    args: Optional[dict] = None
    runner: Optional[str] = None


class PipelineResumeRequest(BaseModel):
    token: str                      # resumeToken handed back by a paused run
    response: Optional[dict] = None # structured answer for an input: gate
    approve: Optional[bool] = None  # yes/no for an approval: gate
    cancel: bool = False            # cancel the workflow instead of continuing
    runner: Optional[str] = None
    background: bool = False        # fire-and-forget: resume runs the (possibly long)
                                    # remaining tail without blocking the HTTP call
    run_id: Optional[str] = None    # the run this decision belongs to, so it lands in
                                    # the run log (the resume token does not carry it)


def _recover_run_spec(source_run_id: str) -> dict:
    """The spec a past run recorded, or a 404/409 saying which is missing.

    Two endpoints did this lookup and told the two failures apart differently:
    /pipeline/rerun distinguished "there is no such run" from "the run predates
    spec recording", /pipeline/rerun-plan collapsed both into the second — so a
    typo'd run id was diagnosed as an old run (review 3, 2026-09-04).
    """
    events = pipeline_runlog.read_events(_checked_run_id(source_run_id, "source_run_id"))
    start = next((e for e in events if e.get("kind") == "run_start"), None)
    if start is None:
        raise HTTPException(status_code=404, detail=f"no run log for {source_run_id!r}")
    spec = start.get("spec")
    if spec is None:
        raise HTTPException(
            status_code=409,
            detail=f"run {source_run_id!r} predates spec recording — "
                   "pass 'spec' explicitly to re-run it",
        )
    return spec


def _pipeline_result_to_dict(res) -> dict:
    """Flatten a PipelineResult for the JSON response (Pilot reads this verbatim).

    The shape lives on the dataclass; this name stays because six call sites
    use it.
    """
    return res.to_dict()


@router.post("/pipeline/run")
async def pipeline_run(req: PipelineRunRequest):
    """Start a HITL workflow headlessly. May pause at a gate (status needs_input)."""
    if not req.pipeline_path.endswith(".lobster"):
        raise HTTPException(status_code=400, detail="pipeline_path must be a .lobster file")
    try:
        res = await run_pipeline(req.pipeline_path, args=req.args, runner=req.runner)
    except PipelineError as e:
        # Transport failure (runner unreachable / no envelope) — not a workflow error.
        raise HTTPException(status_code=502, detail=f"pipeline runner error: {e}")
    return _pipeline_result_to_dict(res)


class PipelineRunSpecRequest(BaseModel):
    name: Optional[str] = None    # a tracked spec under pipelines/specs/ (no extension needed)
    spec: Optional[dict] = None   # an inline spec dict (e.g. from an authoring front-end)
    args: Optional[dict] = None   # variable inputs for the run
    runner: Optional[str] = None


# Where named specs live (host pipelines/specs/ via the pipelines mount).
# Where named specs live. Read through the library so the four readers of this
# directory agree, and so a test can point it somewhere without knowing which
# module happens to hold the constant (review 3, 2026-09-04).
_PIPELINE_SPECS_DIR = pipeline_spec.specs_dir()


@router.post("/pipeline/run-spec")
async def pipeline_run_spec(req: PipelineRunSpecRequest):
    """Compile a mora02 pipeline spec to .lobster and run it (may pause at a gate).

    Pass exactly one of: ``spec`` (an inline spec dict) or ``name`` (a tracked spec
    file in pipelines/specs/, with or without extension). This is the trigger that
    drives the whole spec → compile → run → run-log chain; the compiled .lobster is
    written to the OpenClaw workspace and left for inspection.
    """
    if req.spec is not None:
        # Second door for the same rule as on save: write the implicit wiring
        # down. The builder runs the editor's stack WITHOUT saving it first, so
        # materialising only on save would leave the commonest path implicit -
        # and the spec recorded in the run log (which a partial re-run later
        # reads back) would not say what actually ran. Resolution is unchanged;
        # only the silence goes.
        target = pipeline_spec.materialize_wiring(req.spec)
    elif req.name:
        # The same pattern the flow-library endpoints apply to a name before
        # they build a path from it. This sibling did not, so a name with `..`
        # in it chose which spec file to compile AND RUN (review 3).
        stem = req.name[:-len(Path(req.name).suffix)] if Path(req.name).suffix else req.name
        if not _FLOW_NAME_RE.fullmatch(stem):
            raise HTTPException(status_code=422, detail=f"name: {req.name!r} is not a flow name")
        found = pipeline_spec.resolve_spec_path(req.name)
        match = str(found) if found else None
        if match is None:
            raise HTTPException(
                status_code=404,
                detail=f"no spec named {req.name!r} in {_PIPELINE_SPECS_DIR}",
            )
        target = match
    else:
        raise HTTPException(status_code=400, detail="provide either 'spec' (inline) or 'name'")

    try:
        res = await run_pipeline_spec(target, args=req.args, runner=req.runner)
    except PipelineError as e:
        # Covers compile errors (bad spec / unknown or planned op) and runner transport.
        raise HTTPException(status_code=400, detail=f"pipeline spec error: {e}")
    return _pipeline_result_to_dict(res)


@router.post("/pipeline/rerun")
async def pipeline_rerun(req: PipelineRerunRequest):
    """Re-run a flow partially: recompute what changed, replay the rest.

    Without ``spec`` the one the source run RECORDED is used — not the library
    file, which may have been edited since, and which never existed for a flow
    sent straight from the builder. Passing ``spec`` explicitly is what makes a
    revision possible: hand in a spec with an extra edit step and the unchanged
    parts still come from the earlier run.
    """
    spec = req.spec
    if spec is None:
        spec = await asyncio.to_thread(_recover_run_spec, req.source_run_id)
    try:
        res = await rerun_pipeline_spec(
            spec, source_run_id=req.source_run_id, changed=req.changed,
            overrides=req.overrides, args=req.args, runner=req.runner,
        )
    except PipelineError as e:
        raise HTTPException(status_code=400, detail=f"pipeline rerun error: {e}")
    return _pipeline_result_to_dict(res)


@router.post("/pipeline/rerun-plan")
async def pipeline_rerun_plan(req: PipelineRerunRequest):
    """What a re-run WOULD do — same inputs, nothing executed.

    The honest thing to show before spending GPU minutes: which steps come back
    from the earlier run, which are recomputed, and which approvals stand.
    """
    spec = req.spec
    if spec is None:
        spec = await asyncio.to_thread(_recover_run_spec, req.source_run_id)
    try:
        plan = pipeline_spec.plan_rerun(spec, req.changed)
    except PipelineError as e:
        raise HTTPException(status_code=400, detail=f"invalid spec: {e}")
    return {
        "redo": plan.redo,
        "reuse": plan.reuse,
        "gates_needed": plan.gates_needed,
        "saved_steps": len(plan.reuse),
    }


@router.get("/pipeline/flows")
async def pipeline_flows():
    """The flow LIBRARY — the named flows under pipelines/specs/.

    Each entry is a saved pipeline spec (name + steps). Consumed by the /flow
    authoring tool to offer a picker and to load a flow by name.
    """
    flows = [
        {
            "name": data.get("name") or path.stem,
            "file": path.stem,
            "description": data.get("description", ""),
            "tags": data.get("tags", []),
            "updated": data.get("updated", ""),
            "steps": len(data.get("steps", [])),
        }
        for path, data in await asyncio.to_thread(pipeline_spec.list_specs)
    ]
    return {"flows": flows}


@router.get("/pipeline/flow/{name}")
async def pipeline_flow(name: str):
    """Return one named flow spec (matched by spec name or filename stem)."""
    specs = pipeline_spec.specs_dir()
    if specs.is_dir():
        for p in specs.glob("*.json"):
            try:
                spec = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if spec.get("name") == name or p.stem == name:
                return spec
    raise HTTPException(status_code=404, detail=f"flow {name!r} not found")


# A flow name doubles as its file name, so it has to survive both a file system
# and a URL. The authoring UI slugifies before it posts; this is the guard for
# every other caller.


@router.post("/pipeline/flow/{name}")
async def pipeline_flow_save(name: str, request: Request, overwrite: bool = False):
    """Save an authored flow to pipelines/specs/<name>.json.

    Body = the whole spec: metadata (description, tags) plus steps. It is parsed
    and checked against the vocabulary BEFORE anything touches disk, so the
    library can never hold a flow that fails to load back.

    Ops with status "planned" are allowed here on purpose — a flow may be
    authored ahead of its handler; compiling it is what refuses to run.
    """
    if not _FLOW_NAME_RE.fullmatch(name):
        raise HTTPException(
            status_code=400,
            detail="flow name must be 2-64 chars of lowercase letters, digits and dashes",
        )
    try:
        data = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="body must be JSON")
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="spec must be a JSON object")

    # The URL is the authority — it keeps file name and spec name from drifting.
    data["name"] = name
    try:
        parsed = pipeline_spec.load_spec(data)
    except PipelineError as e:
        raise HTTPException(status_code=422, detail=f"invalid spec: {e}")

    # A reference forward or into nothing can never become valid, so the library
    # refuses it here rather than letting the flow sit there until someone runs
    # it. Ops with status "planned" stay allowed - authoring ahead of a handler
    # is intended; wiring to a step that does not exist is not.
    try:
        pipeline_spec.check_references(parsed)
        pipeline_spec.check_wire_types(parsed)
    except PipelineError as e:
        raise HTTPException(status_code=422, detail=f"invalid wiring: {e}")

    known = pipeline_vocab.op_names()
    unknown = sorted({s.op for s in parsed.steps if isinstance(s, pipeline_spec.OpStep)} - known)
    if unknown:
        raise HTTPException(
            status_code=422, detail=f"unknown ops: {', '.join(unknown)}"
        )

    # Write the implicit wiring down before it reaches disk. A step without `in:`
    # takes the previous step's output, which is invisible in the file and in the
    # builder - fine in a straight chain, silently wrong the moment a flow has two
    # branches. Saving is the right moment: the default keeps working, and what
    # runs is what the file says.
    data = pipeline_spec.materialize_wiring(data)

    data.setdefault("description", "")
    data.setdefault("tags", [])
    data["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    specs = pipeline_spec.specs_dir()
    specs.mkdir(parents=True, exist_ok=True)
    target = specs / f"{name}.json"
    existed = target.exists()
    if existed and not overwrite:
        raise HTTPException(
            status_code=409,
            detail=f"flow {name!r} already exists — pass ?overwrite=true to replace it",
        )
    # Write through a temp file so a crash mid-write cannot leave a half spec
    # that the library endpoint would then skip as unparsable.
    tmp = target.with_name(f".{name}.json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, target)
    # This runs as root inside the container, so a fresh file would land as
    # root:root in the repo checkout and break `git checkout` on the host.
    # Hand it to whoever owns the directory — portable, no uid in config.
    try:
        st = specs.stat()
        os.chown(target, st.st_uid, st.st_gid)
        os.chmod(target, 0o664)
    except OSError:
        pass
    _log.info("flow saved: %s (%d steps, overwrite=%s)", name, len(parsed.steps), existed)
    return {
        "ok": True,
        "name": name,
        "file": target.name,
        "steps": len(parsed.steps),
        "replaced": existed,
        "updated": data["updated"],
    }


@router.delete("/pipeline/flow/{name}")
async def pipeline_flow_delete(name: str):
    """Delete a saved flow.

    The same name rule as the save endpoint guards this one: it allows no dots
    and no slashes, so a traversal like ``../../etc/x`` is rejected before any
    path is built. The authoring UI asks the human first; this endpoint does not.
    """
    if not _FLOW_NAME_RE.fullmatch(name):
        raise HTTPException(
            status_code=400,
            detail="flow name must be 2-64 chars of lowercase letters, digits and dashes",
        )
    target = pipeline_spec.specs_dir() / f"{name}.json"
    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"flow {name!r} not found")
    try:
        target.unlink()
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"could not delete: {e}")
    _log.info("flow deleted: %s", name)
    return {"ok": True, "name": name, "deleted": True}


def _read_run_events(run_id: str):
    """Parse a run's JSONL log into a list of events, or None if it doesn't exist."""
    path = os.path.join(pipeline_runlog.log_dir(), f"{run_id}.jsonl")
    events = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    events.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        return None
    return events


@router.get("/pipeline/runs")
async def pipeline_runs():
    """List recent pipeline runs (newest first) for the Runs view — a summary per run."""
    d = pipeline_runlog.log_dir()
    runs = []

    def _scan() -> list:
        try:
            return sorted(Path(d).glob("*.jsonl"),
                          key=lambda p: p.stat().st_mtime, reverse=True)[:40]
        except OSError:
            return []

    files = await asyncio.to_thread(_scan)
    for p in files:
        events = await asyncio.to_thread(_read_run_events, p.stem) or []
        start = next((e for e in events if e.get("kind") == "run_start"), {})
        steps = [e for e in events if e.get("kind") == "step"]
        result = next((e for e in reversed(events) if e.get("kind") == "run_result"), None)
        last = steps[-1] if steps else None
        try:
            active = (time.time() - p.stat().st_mtime) < 90  # log touched recently
        except OSError:
            active = False
        runs.append({
            "run_id": p.stem,
            "pipeline": start.get("pipeline") or p.stem,
            "args": start.get("args"),
            "ts": start.get("ts"),
            "steps_done": len(steps),
            "last_op": last.get("op") if last else None,
            "last_status": last.get("status") if last else None,
            "failed": any(s.get("status") == "failed" for s in steps),
            "active": active,
            "result": result.get("status") if result else None,
        })
    return {"runs": runs}


# Structural log fields, already mapped above or too bulky for the view: inputs
# and params can carry whole prompts, and the view has its own place for them.
_RUN_VIEW_SKIP = {"kind", "inputs", "params", "out_name"}


@router.get("/pipeline/run/{run_id}")
async def pipeline_run_detail(run_id: str):
    """Full step-by-step detail of one run (for the live Runs view)."""
    # In a thread: the Runs view polls this every three seconds for as long as
    # a run looks alive — which is exactly the window in which this same loop is
    # driving that run's steps. Reading and parsing a growing log file on it
    # competed with the work it was reporting on (review 3, 2026-09-04).
    events = await asyncio.to_thread(_read_run_events, os.path.basename(run_id))
    if events is None:
        raise HTTPException(status_code=404, detail=f"run {run_id!r} not found")
    start = next((e for e in events if e.get("kind") == "run_start"), {})
    result = next((e for e in reversed(events) if e.get("kind") == "run_result"), None)
    steps = []
    for e in events:
        if e.get("kind") != "step":
            continue
        out = e.get("out")
        url = None
        if isinstance(out, str) and out.startswith("asset://"):
            try:
                url = asset_refs.url_for_ref(out)
            except Exception:
                url = None
        entry = {
            "step_id": e.get("step_id"), "op": e.get("op"), "status": e.get("status"),
            "out": out, "out_type": e.get("out_type"), "url": url, "error": e.get("error"),
        }
        # Pass the handler's own "log" fields through - token counts, model name,
        # the truncation flag and its hint. The view renders them (runs.js reads
        # s.truncated, s.hint, s.tokens_out); without this they never left the
        # log file, so a completion cut at max_tokens looked like a whole one.
        # Generic on purpose: a new op attaching a new field needs no change here.
        entry.update({k: v for k, v in e.items()
                      if k not in entry and k not in _RUN_VIEW_SKIP})
        steps.append(entry)
    return {
        "run_id": run_id,
        "pipeline": start.get("pipeline"),
        "args": start.get("args"),
        "ts": start.get("ts"),
        "steps": steps,
        "result": result.get("status") if result else None,
    }


_bg_resume_tasks: set = set()  # keep detached resume tasks referenced until done
_PILOT_URL = os.environ.get("PILOT_URL", "http://pilot:8098")


async def _bg_resume_and_refile(req: "PipelineResumeRequest") -> None:
    """Run a detached resume; if it pauses again at a further gate, ask Pilot to
    re-file that decision into the HITL inbox so multi-gate flows keep working."""
    try:
        res = await resume_pipeline(
            req.token, response=req.response, approve=req.approve,
            cancel=req.cancel, runner=req.runner, run_id=req.run_id,
        )
    except Exception as e:
        # The caller was told "resuming" before any of this was attempted, and
        # the Pilot cleared the inbox item on that answer. So a failure here is
        # invisible everywhere: no inbox item, no HTTP error, and — until now —
        # nothing in the run log either, so the RUNS view showed a flow that
        # simply stops after its last step (review 3, 2026-09-04). The run log
        # is where a run's fate belongs, so that is where this goes.
        _log.exception("background resume failed")
        pipeline_runlog.log_event(
            req.run_id, "run_result", ok=False, status="failed",
            error=f"background resume failed: {e}",
        )
        return
    d = _pipeline_result_to_dict(res)
    if d.get("is_paused") and d.get("resume_token"):
        try:
            async with httpx.AsyncClient(timeout=10.0) as c:
                r = await c.post(f"{_PILOT_URL}/inbox/refile", json=d)
            if r.status_code >= 400:
                raise RuntimeError(f"the inbox answered HTTP {r.status_code}")
        except Exception as e:
            # Same reasoning: a gate nobody can see is a run that waits for ever.
            _log.warning("could not re-file the next gate into the inbox: %s", e)
            pipeline_runlog.log_event(
                req.run_id or d.get("run_id"), "run_result", ok=False,
                status="paused_unfiled",
                error=f"paused at a further gate, but the inbox did not take it: {e}",
            )


@router.post("/pipeline/resume")
async def pipeline_resume(req: PipelineResumeRequest):
    """Resume a paused workflow with the external decision (Pilot inbox click).

    ``background=True`` detaches the resume: the remaining tail (which can be long —
    several video steps after a gate) runs without blocking the HTTP call, so the
    inbox click returns at once and the run continues server-side (visible in the
    run log). A further gate is re-filed into the inbox via the Pilot callback.
    """
    if req.background:
        task = asyncio.create_task(_bg_resume_and_refile(req))
        _bg_resume_tasks.add(task)
        task.add_done_callback(_bg_resume_tasks.discard)
        return {"ok": True, "status": "resuming", "is_paused": False}
    try:
        res = await resume_pipeline(
            req.token,
            response=req.response,
            approve=req.approve,
            cancel=req.cancel,
            runner=req.runner,
            run_id=req.run_id,
        )
    except PipelineError as e:
        raise HTTPException(status_code=502, detail=f"pipeline runner error: {e}")
    return _pipeline_result_to_dict(res)
