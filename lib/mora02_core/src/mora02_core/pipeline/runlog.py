"""mora02_core.pipeline.runlog — append-only JSONL logging for pipeline runs.

One file per run (``<log_dir>/<run_id>.jsonl``), one JSON object per line, one
line per event (``run_start`` / ``step`` / ``run_result`` / …). JSONL is chosen
over a single JSON document because it is append-safe: each event is written the
moment it happens, so a run that crashes mid-way still leaves every prior line
valid and parseable — exactly when the log matters most.

The format is the source of truth; a human-readable view is generated on demand
(see scripts/pipelog.py). ``schema_version`` is stamped on every line so the
shape can grow per build wave (tokens/cost, seed, media specs …) without breaking
old logs.

Hard rule: **logging must never break a pipeline run.** Every write swallows
OSError — a full disk or a missing mount degrades to "no logs", never to a failed
pipeline.

Config (env):
  MORA02_PIPELINE_LOG_DIR   where the .jsonl files go (default /data/pipelines/logs)
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any

# Bump when the event shape changes in a way consumers must notice.
# v2: step events may carry per-step LLM token usage (tokens_in/tokens_out/model),
#     passed through from a handler's result["log"] (Welle 2, text-LLM ops).
SCHEMA_VERSION = 2

_DEFAULT_LOG_DIR = "/data/pipelines/logs"


def log_dir() -> str:
    return os.environ.get("MORA02_PIPELINE_LOG_DIR", _DEFAULT_LOG_DIR)


def new_run_id() -> str:
    """A sortable, unique run id: ``YYYYMMDD_HHMMSS_<8hex>``.

    The timestamp prefix makes the per-run files sort chronologically; the random
    suffix keeps two runs in the same second distinct.
    """
    return datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# A run id becomes a file name, and it arrives from the query string of
# /pipeline/step/<op> — baked in by the compiler, but nothing stopped a caller
# from sending its own. Checked here rather than at each caller: this function
# and its twin in runbucket are the only two places a run id becomes a path
# (review 3, 2026-09-04). The shape is what new_run_id() makes.
RUN_ID_RE = re.compile(r"^[0-9]{8}_[0-9]{6}_[0-9a-f]{8}$")


class BadRunId(ValueError):
    """A run id that cannot name a log file."""


def check_run_id(run_id: str) -> str:
    if not RUN_ID_RE.match(str(run_id or "")):
        raise BadRunId(f"{str(run_id)[:80]!r} is not a run id")
    return run_id


def _path(run_id: str) -> str:
    return os.path.join(log_dir(), f"{check_run_id(run_id)}.jsonl")


def log_event(run_id: str | None, kind: str, **fields: Any) -> None:
    """Append one event line to the run's JSONL file. Never raises.

    A falsy ``run_id`` is a no-op (e.g. a direct step call outside a run).
    """
    if not run_id:
        return
    try:
        os.makedirs(log_dir(), exist_ok=True)
        record = {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "kind": kind,
            "ts": _now_iso(),
            **fields,
        }
        with open(_path(run_id), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except OSError:
        # Logging must never break a run — a disk/mount problem degrades to
        # "no logs", not to a failed pipeline.
        pass
    except BadRunId:
        # A run id that cannot name a file was not made here. Dropping the
        # event is the whole response: the promise above is that logging never
        # breaks a run, and an event nobody can correlate is worth less than
        # that promise.
        pass


def read_events(run_id: str) -> list[dict[str, Any]]:
    """All events of a run, in the order they were written.

    Order carries meaning: gates are reached in spec order, so the Nth
    ``gate_decision`` belongs to the Nth gate. The resume token names no gate, so
    this sequence is the only link between a human decision and the gate it
    answered.
    """
    out: list[dict[str, Any]] = []
    try:
        with open(_path(run_id), encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue  # a torn last line must not hide the rest
    except OSError:
        return []
    return out
