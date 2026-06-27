#!/usr/bin/env python3
"""pipelog — read pipeline run logs (the human view over the JSONL source).

The source of truth is one append-only JSONL file per run in the log dir
(MORA02_PIPELINE_LOG_DIR, default /data/pipelinelogs). This renders it readably;
the .jsonl stays the queryable source (jq/grep/Baserow import).

    scripts/pipelog.py list            # recent runs, newest first
    scripts/pipelog.py show <run_id>   # one run, event by event
    scripts/pipelog.py <cmd> --json    # raw events
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "lib" / "mora02_core" / "src"))

from mora02_core.pipeline import runlog  # noqa: E402


def _read(run_id: str) -> list[dict]:
    path = Path(runlog.log_dir()) / f"{run_id}.jsonl"
    if not path.is_file():
        sys.exit(f"no log for run {run_id!r} at {path}")
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _run_files() -> list[Path]:
    d = Path(runlog.log_dir())
    return sorted(d.glob("*.jsonl"), reverse=True) if d.is_dir() else []


def cmd_list(args) -> int:
    rows = []
    for f in _run_files():
        events = [json.loads(ln) for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()]
        start = next((e for e in events if e["kind"] == "run_start"), {})
        result = next((e for e in events if e["kind"] == "run_result"), {})
        steps = [e for e in events if e["kind"] == "step"]
        rows.append({
            "run_id": f.stem,
            "pipeline": start.get("pipeline", "?"),
            "status": result.get("status", "?"),
            "steps": len(steps),
            "ms": sum(e.get("duration_ms", 0) for e in steps),
        })
    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return 0
    for r in rows:
        print(f"{r['run_id']}  {r['pipeline']:<18} {r['status']:<12} "
              f"{r['steps']} steps  {r['ms']} ms")
    print(f"\n{len(rows)} run(s) in {runlog.log_dir()}")
    return 0


def cmd_show(args) -> int:
    events = _read(args.run_id)
    if args.json:
        print(json.dumps(events, indent=2, ensure_ascii=False))
        return 0
    for e in events:
        kind = e.get("kind")
        ts = e.get("ts", "")
        if kind == "run_start":
            print(f"▶ run_start  {e.get('pipeline')}  spec={e.get('spec_hash')}  "
                  f"steps={e.get('steps')}  args={e.get('args')}")
        elif kind == "step":
            mark = "✓" if e.get("status") == "ok" else "✗"
            out = e.get("out_name") or e.get("out") or ""
            print(f"  {mark} {e.get('step_id')} ({e.get('op')})  "
                  f"{e.get('duration_ms', '?')}ms  → {out}")
            if e.get("error"):
                print(f"      error: {e['error']}")
        elif kind == "run_result":
            print(f"■ run_result  status={e.get('status')}  paused={e.get('is_paused')}")
        else:
            print(f"  · {kind}  {ts}  {e}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="pipelog", description=__doc__)
    ap.add_argument("--json", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").set_defaults(func=cmd_list)
    p_show = sub.add_parser("show")
    p_show.add_argument("run_id")
    p_show.set_defaults(func=cmd_show)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
