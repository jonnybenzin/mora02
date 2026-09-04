#!/usr/bin/env python3
"""Phase 1 of the vocabulary test plan: does a value survive the way in?

On 26 August 2026 a two-step flow exposed nine defects. Three of them were the
same mistake: an op read ``inputs[0]`` where it should have rejoined the whole
input, so everything after the first line was dropped in silence -- and
publish.linkedin would have posted a first paragraph instead of a post.

This script asks the question that would have caught it, in two ways:

  A  Static audit. Every op whose vocabulary entry says it consumes TEXT must
     rejoin its input lines. Ops consuming an image/video/audio ref may read
     ``inputs[0]``, because a ref is one line by definition. The verdict comes
     from the vocabulary, not from a hand-kept list, so a new op is covered the
     day it is added.

  B  Live probe against a running script-runner. The canonical payload from
     payload.txt (paragraphs, umlauts, typographic quotes, emoji, shell
     metacharacters, a 327-character line, a marker in the LAST line) is sent
     through the real step endpoint, and the run log says what arrived.

Usage:
    python3 tests/pipeline/test_passthrough.py          # audit + live probes
    python3 tests/pipeline/test_passthrough.py --static # audit only, no stack

Environment: SCRIPT_RUNNER_URL (default http://127.0.0.1:8096),
MORA02_PIPELINE_LOG_DIR (default /opt/mora02/pipelines/logs).
"""

from __future__ import annotations

import ast
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
# The step handlers moved out of main.py into steps.py when that 3400-line file
# was split (September 2026). This audit reads the dispatch table, so it follows.
MAIN_PY = REPO / "apps/script-runner/app/steps.py"
PAYLOAD = Path(__file__).resolve().parent / "payload.txt"
RUNNER = os.environ.get("SCRIPT_RUNNER_URL", "http://127.0.0.1:8096")
LOG_DIR = Path(os.environ.get("MORA02_PIPELINE_LOG_DIR", "/opt/mora02/pipelines/logs"))
MARKER = "TAILMARKER-7Q4X"

# Input types that arrive as a single asset ref, where inputs[0] is correct.
REF_TYPES = {"image", "video", "audio", "media"}

results: list[tuple[str, str, str]] = []  # (verdict, subject, detail)


def record(ok: bool, subject: str, detail: str) -> None:
    results.append(("PASS" if ok else "FAIL", subject, detail))


# --------------------------------------------------------------- A: static ---

def load_vocab() -> dict:
    """op name -> (consumes, input_type) straight from the vocabulary."""
    sys.path.insert(0, str(REPO / "lib/mora02_core/src"))
    from mora02_core.pipeline import vocab  # noqa: E402  (path set above)

    out = {}
    for op in vocab.all_ops():
        out[op.name] = (op.consumes, op.input_type)
    return out


def handler_sources() -> tuple[dict, dict]:
    """(op -> handler source, function name -> source) from steps.py."""
    src = MAIN_PY.read_text(encoding="utf-8")
    tree = ast.parse(src)
    funcs = {
        node.name: ast.get_source_segment(src, node) or ""
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    mapping = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "_PIPELINE_STEPS" not in targets or not isinstance(node.value, ast.Dict):
            continue
        for key, value in zip(node.value.keys, node.value.values):
            if isinstance(key, ast.Constant) and isinstance(value, ast.Name):
                mapping[key.value] = funcs.get(value.id, "")
    return mapping, funcs


def effective_source(handler: str, funcs: dict) -> str:
    """Handler source plus the source of the helpers it calls.

    db.insert reads its input through _json_from() rather than inline. Without
    following one level of indirection the audit would cry wolf, and a test that
    cries wolf gets ignored - which is how the real defect would slip through.
    """
    parts = [handler]
    for name in re.findall(r"\b(_[a-z_]+)\s*\(", handler):
        if name in funcs and funcs[name] is not handler:
            parts.append(funcs[name])
    return "\n".join(parts)


def reads_whole_input(source: str) -> bool:
    """Does this source consume ALL input lines rather than just the first?"""
    if "join(inputs)" in source:
        return True
    # An op taking many refs iterates instead of joining - equally complete.
    return re.search(r"(for\s+\w+\s+in\s+inputs\b)", source) is not None


def audit_static() -> None:
    vocab_ops = load_vocab()
    handlers, funcs = handler_sources()
    if not handlers:
        record(False, "static audit", "no _PIPELINE_STEPS mapping found in steps.py")
        return

    for op, handler in sorted(handlers.items()):
        consumes, input_type = vocab_ops.get(op, (None, None))
        if consumes is None:
            record(False, f"{op}", "op has a handler but no vocabulary entry (drift)")
            continue
        if consumes == "none":
            continue

        source = effective_source(handler, funcs)
        body = re.sub(r"^\s*(async\s+)?def\s+\w+\([^)]*\)[^:]*:", "", source,
                      flags=re.MULTILINE)
        whole = reads_whole_input(source)
        first_only = re.search(r"inputs\[0\]", source) is not None
        touches_input = "inputs" in body

        # The vocabulary is the contract. Where the handler and the contract
        # disagree, the mismatch itself is the finding - in either direction.
        if not touches_input:
            record(False, f"{op} [{input_type}]",
                   f"vocabulary declares consumes={consumes}, but the handler "
                   "never reads its input")
            continue
        if input_type in REF_TYPES:
            # Iterating over refs is the correct reading for a many-ref op; only a
            # TEXT rejoin means the handler quietly accepts more than the
            # vocabulary promises.
            if "join(inputs)" in body:
                record(False, f"{op} [{input_type}]",
                       "handler also accepts TEXT on stdin, but the vocabulary "
                       f"declares input_type={input_type!r} - contract understated")
            continue

        if whole:
            detail = "reads every input line" + (
                " (indexes inputs[0] too - ref/text discrimination)" if first_only else ""
            )
            record(True, f"{op} [{input_type}]", detail)
        elif first_only:
            record(False, f"{op} [{input_type}]",
                   "reads inputs[0] only - everything after the first line is lost")
        else:
            record(False, f"{op} [{input_type}]",
                   "consumes text but neither rejoins nor iterates - check by hand")


# ----------------------------------------------------------------- B: live ---

def post_step(op: str, body: str, query: str) -> tuple[int, str]:
    req = urllib.request.Request(
        f"{RUNNER}/pipeline/step/{op}?{query}",
        data=body.encode("utf-8"),
        method="POST",
        headers={"Content-Type": "text/plain; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def read_step_event(run_id: str, step_id: str) -> dict | None:
    path = LOG_DIR / f"{run_id}.jsonl"
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("kind") == "step" and event.get("step_id") == step_id:
            return event
    return None


def probe_transport(payload: str) -> None:
    """What does a step actually receive? Any op will do - inputs are assembled
    once, in the route, before the handler sees them. image.edit is used because
    it refuses a text input immediately: no GPU, no API call, no side effect."""
    run_id = f"test-passthrough-{int(time.time())}"
    status, _ = post_step("image.edit", payload, f"run_id={run_id}&step_id=transport")
    event = read_step_event(run_id, "transport")
    if event is None:
        record(False, "transport probe", f"no run-log event (HTTP {status}, run {run_id})")
        return

    got = event.get("inputs") or []
    values = [i.get("value", i.get("ref", "")) for i in got]
    sent = payload.strip("\n").split("\n")

    record(len(values) == len(sent),
           "transport: line count",
           f"sent {len(sent)} lines, step received {len(values)}")
    record(values.count("") == sent.count(""),
           "transport: blank lines (paragraphs)",
           f"sent {sent.count('')} blank lines, step received {values.count('')}")
    record(any(MARKER in v for v in values),
           "transport: last line arrives",
           f"{MARKER} {'found' if any(MARKER in v for v in values) else 'MISSING'}")
    specials = "& < > % # ? = + / \\ ' \" ` $ * | ~ ^"
    record(any(specials in v for v in values),
           "transport: shell metacharacters",
           "special-character line unchanged" if any(specials in v for v in values)
           else "special-character line altered or missing")

    # The run log may shorten a long value - it is a log, not an archive. What it
    # must not do is shorten it in silence: a reader hunting a defect would see a
    # different input than the one that ran.
    longest_sent = max(len(line) for line in sent)
    longest_seen = max((len(v) for v in values), default=0)
    cuts = [i for i in got if i.get("truncated")]
    honest = longest_seen >= longest_sent or (
        cuts and all(i.get("len") for i in cuts)
    )
    if longest_seen >= longest_sent:
        detail = f"longest line ({longest_sent} chars) recorded in full"
    elif cuts:
        detail = (f"shortened to {longest_seen} chars, declared: "
                  f"truncated=True len={cuts[0].get('len')}")
    else:
        detail = (f"longest line sent {longest_sent} chars, recorded "
                  f"{longest_seen} - TRUNCATED without a marker")
    record(bool(honest), "transport: long line in the RUN LOG", detail)


def probe_llm_tail(payload: str) -> None:
    """Does the whole text reach the model, or only its first line? The marker
    sits in the LAST line, so an answer that knows it proves the rejoin."""
    run_id = f"test-passthrough-llm-{int(time.time())}"
    status, body = post_step(
        "llm.extract", payload,
        f"fields=marker&run_id={run_id}&step_id=tail&fmt=out",
    )
    if status != 200:
        record(False, "llm.extract: tail reaches the model",
               f"HTTP {status}: {body[:200]}")
        return
    record(MARKER in body, "llm.extract: tail reaches the model",
           f"marker {'in' if MARKER in body else 'MISSING from'} the answer: {body[:120]}")


def stack_is_up() -> bool:
    try:
        with urllib.request.urlopen(f"{RUNNER}/health", timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def main() -> int:
    payload = PAYLOAD.read_text(encoding="utf-8")
    audit_static()

    if "--static" not in sys.argv:
        if stack_is_up():
            probe_transport(payload)
            probe_llm_tail(payload)
        else:
            record(False, "live probes", f"script-runner not reachable at {RUNNER}")

    width = max(len(s) for _, s, _ in results)
    failed = 0
    for verdict, subject, detail in results:
        if verdict == "FAIL":
            failed += 1
        print(f"{verdict}  {subject.ljust(width)}  {detail}")
    print(f"\n{len(results) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
