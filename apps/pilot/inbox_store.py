"""File-backed store for pending HITL inbox items (ADR-022, Baustein 2b).

A pending item is created when a pipeline run pauses (status ``needs_input`` /
``needs_approval``) and removed once it is resolved. It is persisted as JSON on a
durable, mounted path (``/chathistory`` by default) so a Pilot restart does not
strand a paused pipeline: the workflow itself is parked in Lobster's state; here
we only keep the ``resume_token`` plus the context needed to render the decision.

v1 deliberately uses a small JSON file. The clean follow-up is Baserow (Pilot's
data layer, like sessions/personas) — the functions below are the seam to swap
behind without touching the routes or the UI.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from threading import Lock
from typing import Any

_PATH = Path(os.environ.get("PILOT_INBOX_PATH", "/chathistory/inbox.json"))
_lock = Lock()


def _load() -> dict[str, dict[str, Any]]:
    try:
        return json.loads(_PATH.read_text())
    except (FileNotFoundError, ValueError):
        return {}


def _save(items: dict[str, dict[str, Any]]) -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write: never leave a half-written inbox if we crash mid-save.
    tmp = _PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, indent=2))
    tmp.replace(_PATH)


def add(item: dict[str, Any]) -> dict[str, Any]:
    """Store a new pending item; assigns ``id``, ``created_at``, ``status``."""
    with _lock:
        items = _load()
        item_id = item.get("id") or uuid.uuid4().hex[:12]
        stored = {**item, "id": item_id, "created_at": time.time(), "status": "pending"}
        items[item_id] = stored
        _save(items)
        return stored


def update(item_id: str, **changes: Any) -> dict[str, Any] | None:
    """Patch an existing item (e.g. a new resume_token after a multi-gate resume)."""
    with _lock:
        items = _load()
        item = items.get(item_id)
        if item is None:
            return None
        item.update(changes)
        items[item_id] = item
        _save(items)
        return item


def list_pending() -> list[dict[str, Any]]:
    """All still-open items, oldest first."""
    with _lock:
        items = _load()
    return sorted(
        (i for i in items.values() if i.get("status") == "pending"),
        key=lambda i: i.get("created_at", 0),
    )


def get(item_id: str) -> dict[str, Any] | None:
    with _lock:
        return _load().get(item_id)


def remove(item_id: str) -> None:
    with _lock:
        items = _load()
        items.pop(item_id, None)
        _save(items)
