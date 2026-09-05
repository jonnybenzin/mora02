#!/usr/bin/env python3
"""pipelog — read pipeline run logs (the human view over the JSONL source).

The source of truth is one append-only JSONL file per run in the log dir
(MORA02_PIPELINE_LOG_DIR, default /data/pipelines/logs inside the containers,
/opt/mora02/pipelines/logs on the host). This renders it readably; the .jsonl
stays the queryable source (jq/grep/Baserow import).

    scripts/pipelog.py list              # recent runs, newest first
    scripts/pipelog.py show <run_id>     # one run, event by event, with totals
    scripts/pipelog.py archive <run_id>  # gather the run's outputs into one folder
    scripts/pipelog.py <cmd> --json      # raw events / rows

``archive`` asks the running script-runner to do the copying (it holds the
stores' mounts); SCRIPT_RUNNER_URL overrides http://127.0.0.1:8096.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "lib" / "mora02_core" / "src"))

from mora02_core.pipeline import runlog  # noqa: E402

RUNNER = os.environ.get("SCRIPT_RUNNER_URL", "http://127.0.0.1:8096")


def _read(run_id: str) -> list[dict]:
    path = Path(runlog.log_dir()) / f"{run_id}.jsonl"
    if not path.is_file():
        sys.exit(f"no log for run {run_id!r} at {path}")
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _run_files() -> list[Path]:
    d = Path(runlog.log_dir())
    return sorted(d.glob("*.jsonl"), reverse=True) if d.is_dir() else []


def _totals(events: list[dict]) -> dict:
    """What a run cost, summed over its steps: time, tokens, money."""
    steps = [e for e in events if e.get("kind") == "step"]
    return {
        "steps": len(steps),
        "failed": sum(1 for e in steps if e.get("status") == "failed"),
        "ms": sum(e.get("duration_ms") or 0 for e in steps),
        "tokens_in": sum(e.get("tokens_in") or 0 for e in steps),
        "tokens_out": sum(e.get("tokens_out") or 0 for e in steps),
        "cost_usd": round(sum(e.get("cost_usd") or 0 for e in steps), 6),
        "gates": sum(1 for e in events if e.get("kind") == "gate_decision"),
    }


def _summary(events: list[dict]) -> dict:
    start = next((e for e in events if e.get("kind") == "run_start"), {})
    # The LAST run_result: a resumed run writes one per leg, and the first one
    # is the pause, not the fate.
    result = next((e for e in reversed(events) if e.get("kind") == "run_result"), {})
    return {
        "pipeline": start.get("pipeline", "?"),
        "trigger": start.get("trigger") or "?",
        "batch": start.get("batch"),
        "status": result.get("status", "?"),
        "archived": any(e.get("kind") == "run_archived" for e in events),
        **_totals(events),
    }


def cmd_list(args) -> int:
    rows = []
    for f in _run_files():
        events = [json.loads(ln) for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()]
        rows.append({"run_id": f.stem, **_summary(events)})
    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return 0
    for r in rows:
        cost = f"  ${r['cost_usd']:.4f}" if r["cost_usd"] else ""
        toks = f"  {r['tokens_out']} tok" if r["tokens_out"] else ""
        mark = "  [archived]" if r["archived"] else ""
        if r.get("batch"):
            mark += f"  batch {r['batch'].get('index')}/{r['batch'].get('size')}"
        print(f"{r['run_id']}  {r['pipeline']:<18} {r['trigger']:<9} {r['status']:<12} "
              f"{r['steps']} steps  {r['ms']} ms{toks}{cost}{mark}")
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
                  f"steps={e.get('steps')}  trigger={e.get('trigger')}  args={e.get('args')}")
            if e.get("vocab_hash"):
                print(f"    vocab={e['vocab_hash']}  core={e.get('core_version')}  "
                      f"runner={e.get('runner')} {e.get('runner_version') or ''}")
        elif kind == "step":
            mark = "✓" if e.get("status") == "ok" else ("↺" if e.get("status") == "replayed" else "✗")
            out = e.get("out_name") or e.get("out") or ""
            if isinstance(out, str) and len(out) > 60:
                out = out[:57] + "..."
            print(f"  {mark} {e.get('step_id')} ({e.get('op')})  "
                  f"{e.get('duration_ms', '?')}ms  → {out}")
            facts = e.get("out_file") or {}
            if facts:
                dims = f"  {facts['width']}x{facts['height']}" if facts.get("width") else ""
                dur = f"  {facts['duration_s']}s" if facts.get("duration_s") else ""
                sha = f"  sha256={facts['sha256'][:12]}" if facts.get("sha256") else ""
                print(f"      file: {facts.get('bytes')} bytes{dims}{dur}{sha}")
            if e.get("tokens_out"):
                print(f"      tokens: {e.get('tokens_in', '?')} → {e['tokens_out']}"
                      f"{'  $' + format(e['cost_usd'], '.4f') if e.get('cost_usd') else ''}"
                      f"{'  ' + str(e.get('model')) if e.get('model') else ''}"
                      f"{'  TRUNCATED' if e.get('truncated') else ''}")
            if e.get("error"):
                print(f"      error: {e['error']}")
        elif kind == "gate_decision":
            print(f"◆ gate_decision  {e.get('decision')}  → {e.get('status')}")
        elif kind == "run_result":
            tail = "  (after resume)" if e.get("after") == "resume" else ""
            print(f"■ run_result  status={e.get('status')}  paused={e.get('is_paused')}{tail}")
        elif kind == "run_archived":
            print(f"▣ run_archived  {e.get('files')} files, {e.get('bytes')} bytes → {e.get('path')}")
        else:
            print(f"  · {kind}  {ts}  {e}")
    t = _totals(events)
    print(f"\ntotal: {t['steps']} steps ({t['failed']} failed), {t['ms']} ms, "
          f"{t['tokens_in']} → {t['tokens_out']} tokens, ${t['cost_usd']:.4f}, {t['gates']} gate(s)")
    return 0


def cmd_archive(args) -> int:
    req = urllib.request.Request(f"{RUNNER}/pipeline/run/{args.run_id}/archive", method="POST")
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            manifest = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        sys.exit(f"archive refused: HTTP {e.code} {e.read().decode('utf-8', 'replace')[:200]}")
    except urllib.error.URLError as e:
        sys.exit(f"script-runner not reachable at {RUNNER}: {e.reason}")
    if args.json:
        print(json.dumps(manifest, indent=2, ensure_ascii=False))
        return 0
    print(f"archived {args.run_id} → {manifest.get('path')}")
    for f in manifest.get("files", []):
        if "missing" in f:
            print(f"  ✗ {f['step_id']}: {f.get('ref')}  ({f['missing']})")
        else:
            print(f"  ✓ {f['step_id']}: {f['file']}  ({f.get('bytes', 0)} bytes)")
    print(f"{manifest.get('bytes', 0)} bytes, {manifest.get('missing', 0)} missing")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="pipelog", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").set_defaults(func=cmd_list)
    p_show = sub.add_parser("show")
    p_show.add_argument("run_id")
    p_show.set_defaults(func=cmd_show)
    p_arch = sub.add_parser("archive")
    p_arch.add_argument("run_id")
    p_arch.set_defaults(func=cmd_archive)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
