#!/usr/bin/env python3
"""Does every cut in the pipeline announce itself?

Six of the nine defects found on 26 August 2026 were not malfunctions. The
system worked; it just did not say what it had done. A completion stopped at
512 tokens, a run-log entry stopped at 200 characters, a display stopped at
2000 - each looked exactly like a complete value. That class of defect cannot
be caught by asking "does it work", only by asking "and if it shortens
something, do I find out?"

So this walks the pipeline code, finds every place that shortens something, and
holds each one against truncation-inventory.txt, where every known cut carries
its kind and a written reason. Two verdicts follow:

  * A cut declared "announced" or "data-limit" must have the evidence in the
    code beside it - a truncated flag, a length, a visible note. Claiming to be
    honest is not being honest.
  * A cut that is NOT in the inventory fails, whatever it does. Classifying it
    takes one line; the line then stays as the record of why it is allowed.

Diagnostic cuts - a shortened error body inside a message, a stack tail in a log
line - are exempt: they never masquerade as content. They are counted, not
judged, so their growth stays visible.

Usage: python3 tests/pipeline/test_truncation.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
INVENTORY = Path(__file__).resolve().parent / "truncation-inventory.txt"

SCAN = [
    "apps/script-runner/app/main.py",
    "apps/pilot/app.py",
    "apps/pilot/bot_bridge.py",
    "apps/pilot/ui/js/runs.js",
    "apps/pilot/ui/js/flows.js",
    "apps/pilot/ui/js/flowbuilder.js",
]
SCAN_TREES = ["lib/mora02_core/src/mora02_core"]

# A slice by a literal length, or by a constant whose name is about length.
PY_CUT = re.compile(r"\[:\s*(?:\d{2,}|[A-Za-z_]*(?:MAX|LIMIT|CHARS|max_chars|limit)[A-Za-z_0-9]*)\s*\]")
JS_CUT = re.compile(r"\.(?:slice|substring)\(\s*0\s*,\s*\d{2,}\s*\)")
# Lines where the cut lands inside an error or log message, never in a value.
DIAGNOSTIC = re.compile(r"raise |error|Error|stderr|status_code|_log\.|except |detail|"
                        r"message|uuid|\.hexdigest\(\)\[:8\]")
# What counts as announcing a cut, in Python or in the browser.
EVIDENCE = re.compile(r"truncated|source_chars|gekürzt|Zeichen insgesamt|max_chars|hint")
EVIDENCE_WINDOW = 8  # lines either side

results: list[tuple[str, str, str]] = []


def record(ok: bool, subject: str, detail: str) -> None:
    results.append(("PASS" if ok else "FAIL", subject, detail))


def load_inventory() -> list[dict]:
    entries = []
    for raw in INVENTORY.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 4:
            record(False, "inventory syntax", f"expected 4 fields: {line[:70]}")
            continue
        path, needle, kind, reason = parts
        if not reason:
            record(False, f"inventory: {path}", "entry without a reason grants nothing")
            continue
        entries.append({"path": path, "needle": needle, "kind": kind,
                        "reason": reason, "seen": False})
    return entries


def files_to_scan() -> list[Path]:
    out = [REPO / f for f in SCAN]
    for tree in SCAN_TREES:
        out += sorted((REPO / tree).rglob("*.py"))
    return [f for f in out if f.is_file()]


def main() -> int:
    inventory = load_inventory()
    diagnostic_cuts = 0

    for path in files_to_scan():
        rel = str(path.relative_to(REPO))
        lines = path.read_text(encoding="utf-8").split("\n")
        pattern = JS_CUT if path.suffix == ".js" else PY_CUT

        for i, line in enumerate(lines):
            if not pattern.search(line):
                continue
            if DIAGNOSTIC.search(line):
                diagnostic_cuts += 1
                continue

            entry = next((e for e in inventory
                          if e["path"] == rel and e["needle"] in line), None)
            if entry is None:
                record(False, f"{rel}:{i + 1}",
                       f"cut not in the inventory - classify it: {line.strip()[:70]}")
                continue
            entry["seen"] = True

            if entry["kind"] in ("announced", "data-limit"):
                window = "\n".join(lines[max(0, i - EVIDENCE_WINDOW):i + EVIDENCE_WINDOW])
                if EVIDENCE.search(window):
                    record(True, f"{rel}:{i + 1}",
                           f"{entry['kind']} - and it says so ({entry['reason']})")
                else:
                    record(False, f"{rel}:{i + 1}",
                           f"declared {entry['kind']} but nothing nearby announces the cut")
            else:
                record(True, f"{rel}:{i + 1}", f"{entry['kind']} - {entry['reason']}")

    for entry in inventory:
        if not entry["seen"]:
            record(False, f"inventory: {entry['path']}",
                   f"entry no longer matches any code: {entry['needle']!r} "
                   "(cut removed? then remove the entry)")

    width = max((len(s) for _, s, _ in results), default=10)
    failed = sum(1 for v, _, _ in results if v == "FAIL")
    for verdict, subject, detail in results:
        print(f"{verdict}  {subject.ljust(width)}  {detail}")
    print(f"\n{len(results) - failed} passed, {failed} failed "
          f"({diagnostic_cuts} diagnostic cuts exempt)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
