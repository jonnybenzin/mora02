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
import uuid
from datetime import datetime, timezone
from typing import Any

# Bump when the event shape changes in a way consumers must notice.
SCHEMA_VERSION = 1

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


def _path(run_id: str) -> str:
    return os.path.join(log_dir(), f"{run_id}.jsonl")


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
