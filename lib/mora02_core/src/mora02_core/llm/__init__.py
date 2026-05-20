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
from mora02_core.llm.qwen import stream_qwen
from mora02_core.llm.switcher import (
    get_local_profile_label,
    get_local_profile_name,
)

__all__ = [
    "stream_llm",
    "stream_claude",
    "stream_qwen",
    "MODELS",
    "LOCAL_PROFILE_LABELS",
    "get_local_profile_name",
    "get_local_profile_label",
]
