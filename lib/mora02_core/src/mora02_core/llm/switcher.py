"""Read-only bridge to the local-LLM profile switcher.

Single source of truth is /llm-switch/current.json, written by
/opt/mora02/scripts/llm-switch.sh on every successful switch.
The file is mounted into containers that need to read it.
"""

import json
from pathlib import Path

from mora02_core.llm.models import LOCAL_PROFILE_LABELS

_LLM_CURRENT_STATE_FILE = Path("/llm-switch/current.json")


def get_local_profile_name() -> str | None:
    """Return the currently active local-LLM profile key, or None if unknown."""
    try:
        data = json.loads(_LLM_CURRENT_STATE_FILE.read_text())
        name = data.get("profile")
        return name if isinstance(name, str) and name else None
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def get_local_profile_label() -> str:
    """Return a human label for the current local profile, or 'Local LLM'."""
    name = get_local_profile_name()
    if not name:
        return "Local LLM"
    return LOCAL_PROFILE_LABELS.get(name, name)
