"""mora02_core.llm — streaming LLM clients (local Qwen + Anthropic Claude).

Phase 1.3: extracted from apps/pilot/llm_client.py + apps/pilot/config.py.
PROFILES (use-case → model mapping) is deferred until a real caller exists.

Recommended for new code:

    from mora02_core.llm import stream_llm, MODELS
    async for chunk in stream_llm(messages, "You are helpful", model_key="sonnet"):
        ...
"""

from mora02_core.llm.claude_api import stream_claude
from mora02_core.llm.client import stream_llm
from mora02_core.llm.models import LOCAL_PROFILE_LABELS, MODELS
from mora02_core.llm.profiles import PROFILES, profile_label, profile_names
from mora02_core.llm.qwen import stream_qwen
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

__all__ = [
    "stream_llm",
    "stream_claude",
    "stream_qwen",
    "MODELS",
    "LOCAL_PROFILE_LABELS",
    "PROFILES",
    "profile_label",
    "profile_names",
    "LLMSwitchError",
    "get_local_profile_name",
    "get_local_profile_label",
    "get_current_profile",
    "list_profiles",
    "submit_switch",
    "get_switch_status",
    "switch_profile_blocking",
]
