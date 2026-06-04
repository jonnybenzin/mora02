"""Local-LLM profile switcher — read state and submit switch requests.

The actual switch is performed by the host-side script
``/opt/mora02/scripts/llm-switch.sh``, triggered by an
``llm-switch.path`` systemd unit. Containers have no Docker daemon
access; they communicate with the host via a tiny request/response
file briefkasten under ``/llm-switch/`` (bind-mounted in).

Read side: ``/llm-switch/current.json`` is the single source of truth
for "which profile is loaded right now".

Write side: containers drop request files into ``/llm-switch/requests/``
and poll ``/llm-switch/responses/`` for the host's answer.
"""

import json
import re
import time
import uuid
from pathlib import Path
from typing import Optional

from mora02_core.llm.profiles import PROFILES, profile_names


_LLM_SWITCH_DIR = Path("/llm-switch")
_REQUESTS_DIR = _LLM_SWITCH_DIR / "requests"
_RESPONSES_DIR = _LLM_SWITCH_DIR / "responses"
_CURRENT_STATE_FILE = _LLM_SWITCH_DIR / "current.json"

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class LLMSwitchError(Exception):
    """Raised on invalid profile names or briefkasten IO problems."""


# ---------------------------------------------------------------------------
# Read side — used by Pilot for the identity block and by the UI dashboard
# ---------------------------------------------------------------------------


def get_local_profile_name() -> str | None:
    """Return the currently active local-LLM profile key, or None if unknown."""
    try:
        data = json.loads(_CURRENT_STATE_FILE.read_text())
        name = data.get("profile")
        return name if isinstance(name, str) and name else None
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def get_local_profile_label() -> str:
    """Return a human label for the current local profile, or 'Local LLM'."""
    name = get_local_profile_name()
    if not name:
        return "Local LLM"
    return PROFILES.get(name, {}).get("label", name)


def get_current_profile() -> Optional[dict]:
    """Return the currently active profile enriched with metadata.

    Returns None if the state file is missing or unreadable. If the active
    profile name is not in the PROFILES catalog (whitelist drift), a minimal
    dict with just name and label is returned.
    """
    if not _CURRENT_STATE_FILE.exists():
        return None
    try:
        data = json.loads(_CURRENT_STATE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return None

    name = data.get("profile")
    if not name:
        return None

    meta = PROFILES.get(name)
    if meta is not None:
        return {"name": name, **meta, "since": data.get("timestamp")}
    return {"name": name, "label": name, "since": data.get("timestamp")}


def list_profiles() -> list[dict]:
    """Return all available LLM profiles with metadata, as a list for HTTP."""
    return [{"name": name, **meta} for name, meta in PROFILES.items()]


# ---------------------------------------------------------------------------
# Write side — submit a switch request, poll for the response
# ---------------------------------------------------------------------------


def submit_switch(profile_name: str) -> str:
    """Submit a switch request to the host. Returns the request_id immediately.

    Use ``get_switch_status(request_id)`` to poll, or
    ``switch_profile_blocking(profile_name)`` for a convenience wrapper.
    """
    if profile_name not in profile_names():
        raise LLMSwitchError(f"invalid profile: {profile_name}")

    if not _REQUESTS_DIR.exists():
        raise LLMSwitchError(
            f"{_REQUESTS_DIR} not found — is /opt/mora02/llm-switch mounted "
            "into the container and is the host-side installer finished?"
        )

    request_id = f"sr-{uuid.uuid4().hex[:12]}"
    payload = {"request_id": request_id, "profile": profile_name}

    tmp_path = _REQUESTS_DIR / f".{request_id}.tmp"
    final_path = _REQUESTS_DIR / f"{request_id}.json"

    try:
        tmp_path.write_text(json.dumps(payload))
        tmp_path.rename(final_path)  # atomic within same FS
    except OSError as e:
        raise LLMSwitchError(f"failed to write request: {e}") from e

    return request_id


def get_switch_status(request_id: str) -> Optional[dict]:
    """Read the response file for a given request_id.

    Returns the response dict if the host has answered, or None if still
    pending or the file is mid-write. Raises LLMSwitchError on malformed
    request_id (defensive against path-traversal).
    """
    if not _REQUEST_ID_RE.match(request_id):
        raise LLMSwitchError("invalid request_id format")

    response_path = _RESPONSES_DIR / f"{request_id}.json"
    if not response_path.exists():
        return None

    try:
        return json.loads(response_path.read_text())
    except json.JSONDecodeError:
        # File exists but is mid-write — treat as pending
        return None
    except OSError:
        return None


def switch_profile_blocking(
    profile_name: str, timeout: float = 180.0, poll_interval: float = 0.5
) -> dict:
    """Submit a switch and block until the response arrives or timeout hits.

    Used mostly for tests and CLI debugging. The HTTP layer should prefer
    submit_switch + get_switch_status to keep the request non-blocking.
    """
    request_id = submit_switch(profile_name)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = get_switch_status(request_id)
        if result is not None:
            return result
        time.sleep(poll_interval)
    raise LLMSwitchError(f"timeout after {timeout}s waiting for {request_id}")
