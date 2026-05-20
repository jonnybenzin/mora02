"""Anthropic Claude streaming via the official SDK."""

from typing import AsyncGenerator, Optional

import anthropic

from mora02_core import auth
from mora02_core._common import get_logger
from mora02_core.llm.models import MODELS

_log = get_logger("mora02_core.llm.claude_api")


async def stream_claude(
    messages: list[dict],
    system_prompt: str,
    model_key: str = "sonnet",
    image_data: Optional[dict] = None,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    *,
    user_id: str = "default",
) -> AsyncGenerator[dict, None]:
    """Stream from Anthropic. Supports base64 image attachment on the last user message."""
    _log.debug(
        "stream_claude user=%s model=%s msgs=%d image=%s max_tokens=%d",
        user_id, model_key, len(messages), bool(image_data), max_tokens,
    )
    model_config = MODELS[model_key]
    client = anthropic.AsyncAnthropic(api_key=auth.require("ANTHROPIC_API_KEY"))

    api_messages = []
    for msg in messages:
        if msg["role"] == "assistant":
            api_messages.append(msg)
        elif msg["role"] == "user":
            if image_data and msg == messages[-1]:
                api_messages.append({
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {
                            "type": "base64",
                            "media_type": image_data["media_type"],
                            "data": image_data["data"]}},
                        {"type": "text", "text": msg["content"]},
                    ],
                })
            else:
                api_messages.append(msg)

    input_tokens = 0
    output_tokens = 0

    async with client.messages.stream(
        model=model_config["name"], max_tokens=max_tokens,
        system=system_prompt, messages=api_messages,
        temperature=temperature,
    ) as stream:
        async for event in stream:
            if event.type == "content_block_delta" and hasattr(event.delta, "text"):
                yield {"type": "text", "content": event.delta.text}
            elif event.type == "message_start":
                usage = getattr(event.message, "usage", None)
                if usage:
                    input_tokens = usage.input_tokens
            elif event.type == "message_delta":
                usage = getattr(event, "usage", None)
                if usage:
                    output_tokens = usage.output_tokens

    yield {"type": "done", "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens}}
