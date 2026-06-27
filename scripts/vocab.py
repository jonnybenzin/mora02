#!/usr/bin/env python3
"""vocab — query the pipeline step vocabulary from the terminal.

A human-friendly view over the single-source-of-truth registry in
mora02_core.pipeline.vocab (same data as GET /pipeline/ops and the generated
docs/pipeline-vocabulary.md). Rapid lookup without grepping the markdown.

    scripts/vocab.py list                # all ops, one line each
    scripts/vocab.py list --planned      # only not-yet-built ops
    scripts/vocab.py list --bucket audio # filter by service bucket
    scripts/vocab.py show tts.speak      # full detail of one op
    scripts/vocab.py search audio        # full-text over name/summary/bucket
    scripts/vocab.py <cmd> --json        # machine-readable output
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "lib" / "mora02_core" / "src"))

from mora02_core.pipeline import vocab  # noqa: E402

_BADGE = {"wired": "🟢", "planned": "🟡"}


def _line(op) -> str:
    consumes = op.consumes + ("?" if op.consumes_optional else "")
    return (
        f"{_BADGE.get(op.status, ' ')} {op.name:<20} "
        f"{op.bucket:<9} {consumes:<6} {op.input_type}→{op.output_type}"
    )


def _select(args) -> list:
    ops = list(vocab.all_ops())
    if getattr(args, "planned", False):
        ops = [o for o in ops if o.status == "planned"]
    if getattr(args, "wired", False):
        ops = [o for o in ops if o.status == "wired"]
    if getattr(args, "bucket", None):
        ops = [o for o in ops if o.bucket == args.bucket]
    return ops


def cmd_list(args) -> int:
    ops = _select(args)
    if args.json:
        print(json.dumps([o.to_dict() for o in ops], indent=2, ensure_ascii=False))
        return 0
    for op in ops:
        print(_line(op))
    print(f"\n{len(ops)} ops "
          f"({sum(o.status == 'wired' for o in ops)} wired, "
          f"{sum(o.status == 'planned' for o in ops)} planned)")
    return 0


def cmd_show(args) -> int:
    op = vocab.get_op(args.name)
    if op is None:
        print(f"unknown op {args.name!r}; try `vocab search`", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(op.to_dict(), indent=2, ensure_ascii=False))
        return 0
    print(f"{_BADGE.get(op.status, '')} {op.name}   [{op.status}]  bucket={op.bucket}")
    print(f"\n  {op.summary}\n")
    print(f"  default step id : {op.default_id}")
    consumes = op.consumes + (" (optional)" if op.consumes_optional else "")
    print(f"  consumes (stdin): {consumes} ({op.input_type})")
    print(f"  emits (stdout)  : {op.output_type}")
    if op.params:
        print("\n  params:")
        for p in op.params:
            req = " required" if p.required else ""
            default = f" =default {p.default}" if p.default is not None else ""
            choices = f" {list(p.choices)}" if p.choices else ""
            print(f"    - {p.name} ({p.type}){req}{default}{choices}")
            if p.desc:
                print(f"        {p.desc}")
    else:
        print("\n  params: (none)")
    return 0


def cmd_search(args) -> int:
    q = args.term.lower()
    hits = [o for o in vocab.all_ops()
            if q in o.name.lower() or q in o.summary.lower() or q in o.bucket.lower()]
    if args.json:
        print(json.dumps([o.to_dict() for o in hits], indent=2, ensure_ascii=False))
        return 0
    for op in hits:
        print(_line(op))
    print(f"\n{len(hits)} match(es) for {args.term!r}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="vocab", description=__doc__)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="list ops")
    p_list.add_argument("--planned", action="store_true")
    p_list.add_argument("--wired", action="store_true")
    p_list.add_argument("--bucket")
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="show one op in detail")
    p_show.add_argument("name")
    p_show.set_defaults(func=cmd_show)

    p_search = sub.add_parser("search", help="full-text search")
    p_search.add_argument("term")
    p_search.set_defaults(func=cmd_search)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
