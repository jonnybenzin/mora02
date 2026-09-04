#!/usr/bin/env python3
"""Render the agent roster from the repo into the OpenClaw volume.

The shell door to ``mora02_core.agents.deploy``; the browser door is
``POST /agents/deploy`` in script-runner. Same mechanism, read the module for
the reasoning. This file only turns flags into arguments and a result into an
exit code.

    python3 scripts/agents-deploy.py --check     what would change (exit 1 if any)
    python3 scripts/agents-deploy.py             apply it
    python3 scripts/agents-deploy.py --agent researcher

Exit codes: 0 in sync (or brought in sync), 1 drift found / still left,
2 the roster or the gateway refused.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "lib" / "mora02_core" / "src"))

from mora02_core.agents import deploy  # noqa: E402
from mora02_core.agents.store import roots  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true",
                    help="report drift and change nothing (exit 1 if there is any)")
    ap.add_argument("--agent", help="only this agent (the config list is still written whole)")
    args = ap.parse_args()

    # Both roots as the checkout has them: the shipped agents/ and this
    # installation's data/agents/ (absent on a fresh clone, and that is fine).
    local = REPO / "data" / "agents"
    result = deploy.run(check=args.check, only=args.agent,
                        rt=roots(REPO / "agents", local if local.is_dir() else None),
                        say=lambda line: print("  " + line))

    if result["error"] and not result["applied"]:
        print(f"error: {result['error']}", file=sys.stderr)
        return 2
    # Seen and left alone -- a hand-made gateway agent. Shown, never a reason
    # for an exit code: it is not drift.
    for line in result.get("notes") or []:
        print("  note: " + line)
    if result["in_sync"] and not result["applied"]:
        print("in sync — the volume matches the repo")
        return 0
    if args.check:
        print(f"{len(result['drift'])} difference(s):")
        for line in result["drift"]:
            print("  " + line)
        return 1
    if result["error"]:
        print(f"error: {result['error']}", file=sys.stderr)
        return 2
    if result["left"]:
        print("\nstill different after applying:")
        for line in result["left"]:
            print("  " + line)
        return 1
    print("\ndone — in sync")
    return 0


if __name__ == "__main__":
    sys.exit(main())
