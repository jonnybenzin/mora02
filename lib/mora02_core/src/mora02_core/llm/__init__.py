"""mora02_core.llm — streaming LLM clients (local Qwen + Anthropic Claude).

Phase 1.3: extracted from apps/pilot/llm_client.py + apps/pilot/config.py.

Recommended for new code:

    from mora02_core.llm import stream_llm, MODELS
    async for chunk in stream_llm(messages, "You are helpful", model_key="sonnet"):
        ...

Re-exports resolve lazily (PEP 562). Importing this package used to execute
``claude_api`` and therefore require the Anthropic SDK — so a plain host python
could not read the local profile catalogue or submit a model switch, neither of
which has anything to do with Claude. Names now load on first use: reading
PROFILES costs ``profiles.py`` and nothing else, while ``stream_claude`` still
pulls in what it needs, exactly as before. Nothing changes for callers.
"""

from typing import TYPE_CHECKING

# name -> the module that actually defines it
_EXPORTS = {
    "stream_claude": "mora02_core.llm.claude_api",
    "complete_claude_usage": "mora02_core.llm.claude_api",
    "stream_llm": "mora02_core.llm.client",
    "LOCAL_PROFILE_LABELS": "mora02_core.llm.models",
    "MODELS": "mora02_core.llm.models",
    "PROFILES": "mora02_core.llm.profiles",
    "profile_label": "mora02_core.llm.profiles",
    "profile_names": "mora02_core.llm.profiles",
    "stream_qwen": "mora02_core.llm.qwen",
    "complete_qwen": "mora02_core.llm.qwen",
    "complete_qwen_usage": "mora02_core.llm.qwen",
    "LLMSwitchError": "mora02_core.llm.switcher",
    "get_current_profile": "mora02_core.llm.switcher",
    "get_local_profile_label": "mora02_core.llm.switcher",
    "get_local_profile_name": "mora02_core.llm.switcher",
    "get_switch_status": "mora02_core.llm.switcher",
    "list_profiles": "mora02_core.llm.switcher",
    "submit_switch": "mora02_core.llm.switcher",
    "switch_profile_blocking": "mora02_core.llm.switcher",
}


def __getattr__(name: str):
    """Resolve a re-export on first access, then cache it in the module."""
    module_path = _EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    value = getattr(importlib.import_module(module_path), name)
    globals()[name] = value  # second access skips this function entirely
    return value


def __dir__() -> list[str]:
    return sorted(__all__)


if TYPE_CHECKING:  # editors and type checkers still see the real definitions
    from mora02_core.llm.claude_api import stream_claude, complete_claude_usage
    from mora02_core.llm.client import stream_llm
    from mora02_core.llm.models import LOCAL_PROFILE_LABELS, MODELS
    from mora02_core.llm.profiles import PROFILES, profile_label, profile_names
    from mora02_core.llm.qwen import stream_qwen, complete_qwen, complete_qwen_usage
    from mora02_core.llm.switcher import (
        LLMSwitchError,
        get_current_profile,
        get_local_profile_label,
        get_local_profile_name,
        get_switch_status,
        list_profiles,
        submit_switch,
        switch_profile_blocking,
    )

__all__ = list(_EXPORTS)
