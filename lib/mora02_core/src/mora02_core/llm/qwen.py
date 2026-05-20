"""Local LLM streaming via llama.cpp's OpenAI-compatible /v1/chat/completions."""

import json
from typing import AsyncGenerator

import httpx

from mora02_core._common import get_logger
from mora02_core.llm.models import MODELS

_log = get_logger("mora02_core.llm.qwen")


async def stream_qwen(
    messages: list[dict],
    system_prompt: str,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    *,
    user_id: str = "default",
) -> AsyncGenerator[dict, None]:
    """Stream from local llama.cpp. The 'model' field is ignored by the server."""
    _log.debug("stream_qwen user=%s msgs=%d max_tokens=%d", user_id, len(messages), max_tokens)
    payload = {
        "model": "local",
        "messages": [{"role": "system", "content": system_prompt}] + messages,
        "stream": True,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream(
            "POST", MODELS["qwen"]["endpoint"],
            json=payload, headers={"Content-Type": "application/json"},
        ) as resp:
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    yield {"type": "done", "usage": {"input_tokens": 0, "output_tokens": 0}}
                    return
                try:
                    chunk = json.loads(data)
                    delta = chunk["choices"][0].get("delta", {})
                    if "content" in delta and delta["content"]:
                        yield {"type": "text", "content": delta["content"]}
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
