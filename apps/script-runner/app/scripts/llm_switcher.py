"""
LLM Profile Switcher — client for host-side systemd switcher.

Writes request files to /llm-switch/requests/ and reads responses from
/llm-switch/responses/. The host-side llm-switch.sh (triggered by
llm-switch.path systemd unit) processes the requests. Script-Runner itself
has NO Docker daemon access — the security boundary is on the host.

Profile metadata here MUST stay in sync with the whitelist in
/opt/mora02/scripts/llm-switch.sh.
"""

import json
import re
import time
import uuid
from pathlib import Path
from typing import Optional

# ----------------------------------------------------------------------------
# Paths — inside the container, /llm-switch is bind-mounted from the host
# ----------------------------------------------------------------------------

LLM_SWITCH_DIR = Path("/llm-switch")
REQUESTS_DIR = LLM_SWITCH_DIR / "requests"
RESPONSES_DIR = LLM_SWITCH_DIR / "responses"
CURRENT_STATE_FILE = LLM_SWITCH_DIR / "current.json"

# ----------------------------------------------------------------------------
# Profile metadata — must match whitelist in llm-switch.sh
# ----------------------------------------------------------------------------

PROFILES = [
    {
        "name": "qwen3-14b",
        "label": "Qwen3 14B",
        "category": "Balanced",
        "model": "Qwen3-14B-Q4_K_M.gguf",
        "vram": "~15.5 GB",
        "description": "Default general-purpose",
    },
    {
        "name": "qwen3-8b",
        "label": "Qwen3 8B",
        "category": "Fast",
        "model": "Qwen3-8B-Q4_K_M.gguf",
        "vram": "~9 GB",
        "description": "Faster, lower VRAM",
    },
    {
        "name": "qwen25-7b",
        "label": "Qwen2.5 7B",
        "category": "Fast",
        "model": "Qwen2.5-7B-Instruct-Q4_K_M.gguf",
        "vram": "~8 GB",
        "description": "Instruction-tuned",
    },
    {
        "name": "qwen25-coder",
        "label": "Qwen2.5 Coder",
        "category": "Code",
        "model": "qwen2.5-coder-14b-instruct-q4_k_m.gguf",
        "vram": "~15.5 GB",
        "description": "Code-specialized 14B",
    },
    {
        "name": "nous-hermes",
        "label": "Nous-Hermes",
        "category": "Balanced",
        "model": "nous-hermes-2-mistral-7b-q4_k_m.gguf",
        "vram": "~8 GB",
        "description": "Chat-tuned Mistral 7B",
    },
    {
        "name": "magistral",
        "label": "Magistral",
        "category": "Reasoning",
        "model": "Magistral-Small-2506-Q4_K_M.gguf",
        "vram": "~25 GB",
        "description": "Long-chain reasoning 24B",
    },
]

VALID_PROFILE_NAMES = {p["name"] for p in PROFILES}

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class LLMSwitchError(Exception):
    """Raised on invalid input or IO problems talking to the briefkasten."""


# ----------------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------------


def list_profiles() -> list[dict]:
    """Return all available LLM profiles with metadata."""
    return list(PROFILES)


def get_current_profile() -> Optional[dict]:
    """
    Return the currently active profile (enriched with metadata), or None
    if unknown. Reads /llm-switch/current.json which is maintained by
    llm-switch.sh on every successful switch.
    """
    if not CURRENT_STATE_FILE.exists():
        return None
    try:
        data = json.loads(CURRENT_STATE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return None

    name = data.get("profile")
    if not name:
        return None

    for p in PROFILES:
        if p["name"] == name:
            return {**p, "since": data.get("timestamp")}

    # Unknown profile name (whitelist drift) — return minimal info
    return {"name": name, "label": name, "since": data.get("timestamp")}


def submit_switch(profile_name: str) -> str:
    """
    Submit a switch request. Returns the request_id immediately without
    waiting for the host service to finish. Use get_switch_status() to poll.
    """
    if profile_name not in VALID_PROFILE_NAMES:
        raise LLMSwitchError(f"invalid profile: {profile_name}")

    if not REQUESTS_DIR.exists():
        raise LLMSwitchError(
            f"{REQUESTS_DIR} not found — is /opt/mora02/llm-switch mounted "
            "into the container and is the host-side installer finished?"
        )

    request_id = f"sr-{uuid.uuid4().hex[:12]}"
    payload = {"request_id": request_id, "profile": profile_name}

    tmp_path = REQUESTS_DIR / f".{request_id}.tmp"
    final_path = REQUESTS_DIR / f"{request_id}.json"

    try:
        tmp_path.write_text(json.dumps(payload))
        tmp_path.rename(final_path)  # atomic within same FS
    except OSError as e:
        raise LLMSwitchError(f"failed to write request: {e}") from e

    return request_id


def get_switch_status(request_id: str) -> Optional[dict]:
    """
    Read the response file for a given request_id.
    Returns the response dict if the host has answered, or None if still
    pending. Raises LLMSwitchError on malformed request_id.
    """
    if not _REQUEST_ID_RE.match(request_id):
        raise LLMSwitchError("invalid request_id format")

    response_path = RESPONSES_DIR / f"{request_id}.json"
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
    """
    Convenience wrapper: submit a switch and block until the response arrives
    or timeout is hit. Returns the response dict. Raises LLMSwitchError on
    timeout. Used mostly for tests and CLI debugging — the HTTP layer should
    prefer submit_switch + get_switch_status.
    """
    request_id = submit_switch(profile_name)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = get_switch_status(request_id)
        if result is not None:
            return result
        time.sleep(poll_interval)
    raise LLMSwitchError(f"timeout after {timeout}s waiting for {request_id}")
