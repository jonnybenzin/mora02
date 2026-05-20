"""Top-level dispatcher: route to qwen or claude based on MODELS[key]['type']."""

from typing import AsyncGenerator, Optional

from mora02_core._common import get_logger
from mora02_core.llm.claude_api import stream_claude
from mora02_core.llm.models import MODELS
from mora02_core.llm.qwen import stream_qwen

_log = get_logger("mora02_core.llm.client")


async def stream_llm(
    messages: list[dict],
    system_prompt: str,
    model_key: str = "qwen",
    image_data: Optional[dict] = None,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    *,
    user_id: str = "default",
) -> AsyncGenerator[dict, None]:
    """Dispatch to the right backend by looking up MODELS[model_key]['type'].

    'openai_compatible' → local llama.cpp via stream_qwen (no image_data).
    'anthropic'         → Anthropic SDK via stream_claude (image_data supported).
    """
    model = MODELS.get(model_key)
    if not model:
        raise ValueError(f"Unknown model_key: {model_key!r}")
    model_type = model.get("type")
    if model_type == "openai_compatible":
        async for chunk in stream_qwen(
            messages, system_prompt, temperature, max_tokens, user_id=user_id,
        ):
            yield chunk
    elif model_type == "anthropic":
        async for chunk in stream_claude(
            messages, system_prompt, model_key, image_data, temperature, max_tokens,
            user_id=user_id,
        ):
            yield chunk
    else:
        raise ValueError(
            f"Model {model_key!r} has unsupported type {model_type!r} "
            f"(expected 'openai_compatible' or 'anthropic')"
        )
