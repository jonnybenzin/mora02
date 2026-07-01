"""mora02_core.pipeline.runbucket — run-scoped output store for non-linear flow.

The linear pipeline pipes ONE value per step via stdin. But a step often needs to
pull the *named* outputs of EARLIER steps into specific param fields — e.g.
``music.generate`` taking one LLM step's output as ``prompt`` and another's as
``lyrics``. Lobster cannot interpolate step outputs into the run command (only via
``stdin:``), so the fan-in is resolved in the executor (the script-runner step
endpoint): after each step, its output is :func:`put` here under
``(run_id, step_id)``; a later step whose spec param is ``{"from": "<id>"}`` is
compiled to ``__ref_<param>=<id>`` and resolved by :func:`get` before the handler
runs.

One JSON file per run (``<bucket_dir>/<run_id>.json``), a flat ``{step_id: output}``
map. Steps in a run execute sequentially, so read-modify-write needs no locking.

Config (env):
  MORA02_PIPELINE_BUCKET_DIR   where the .json files go (default /data/pipelines/bucket)
"""

from __future__ import annotations

import json
import os
from typing import Any

from mora02_core._common import get_logger

_log = get_logger("mora02_core.pipeline.runbucket")

_DEFAULT_BUCKET_DIR = "/data/pipelines/bucket"


def bucket_dir() -> str:
    return os.environ.get("MORA02_PIPELINE_BUCKET_DIR", _DEFAULT_BUCKET_DIR)


def _path(run_id: str) -> str:
    return os.path.join(bucket_dir(), f"{run_id}.json")


def _load(run_id: str) -> dict[str, Any]:
    try:
        with open(_path(run_id), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def put(run_id: str | None, step_id: str, value: Any) -> None:
    """Store a step's output under its id for the run. No-op without a run_id.

    Best-effort like the run log: a failed write degrades to "the ref won't
    resolve downstream" (a clear error at the consuming step), never a crash of
    the producing step, which has already done its real work.
    """
    if not run_id:
        return
    try:
        data = _load(run_id)
        data[step_id] = value
        os.makedirs(bucket_dir(), exist_ok=True)
        tmp = _path(run_id) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, default=str)
        os.replace(tmp, _path(run_id))  # atomic swap
    except OSError as e:
        _log.warning("runbucket put failed for %s/%s: %s", run_id, step_id, e)


def get(run_id: str | None, step_id: str) -> Any:
    """Fetch an earlier step's stored output. Raises KeyError if absent."""
    data = _load(run_id) if run_id else {}
    if step_id not in data:
        raise KeyError(step_id)
    return data[step_id]
