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


async def complete_qwen_usage(
    messages: list[dict],
    system_prompt: str,
    *,
    temperature: float = 0.7,
    max_tokens: int = 512,
    user_id: str = "default",
    think: bool = False,
) -> tuple[str, dict]:
    """Non-streaming completion that ALSO returns token usage.

    Same call as :func:`complete_qwen`, but returns ``(content, usage)`` where
    ``usage`` is ``{"tokens_in", "tokens_out", "model"}`` drawn from llama.cpp's
    response. Pipeline LLM steps use this to log per-step token counts; callers
    that only want the text use the :func:`complete_qwen` wrapper below.

    Qwen3 routes its chain-of-thought to a separate ``reasoning_content`` field;
    a long think can exhaust ``max_tokens`` before any ``content`` is emitted,
    yielding an empty answer. So value callers disable it via the ``/no_think``
    soft switch (``think=False``, the default). The ``reasoning_content`` fallback
    keeps us non-empty even if a server build ignores the switch.
    """
    _log.debug("complete_qwen user=%s msgs=%d max_tokens=%d think=%s",
               user_id, len(messages), max_tokens, think)
    system = system_prompt if think else f"{system_prompt}\n/no_think"
    payload = {
        "model": "local",
        "messages": [{"role": "system", "content": system}] + messages,
        "stream": False,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            MODELS["qwen"]["endpoint"],
            json=payload, headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
    message = data["choices"][0]["message"]
    content = (message.get("content") or "").strip()
    if not content:
        content = (message.get("reasoning_content") or "").strip()
    usage_raw = data.get("usage") or {}
    usage = {
        "tokens_in": usage_raw.get("prompt_tokens"),
        "tokens_out": usage_raw.get("completion_tokens"),
        "model": data.get("model"),  # llama.cpp echoes the served model name
    }
    return content, usage


async def complete_qwen(
    messages: list[dict],
    system_prompt: str,
    *,
    temperature: float = 0.7,
    max_tokens: int = 512,
    user_id: str = "default",
    think: bool = False,
) -> str:
    """Non-streaming completion from local llama.cpp — the whole text at once.

    For callers that want the answer, not an incremental stream — e.g. a pipeline
    value step that produces a single prompt/summary. Local-only (control-plane
    guardrail). Distinct from :func:`stream_qwen` (used by the Pilot chat, which
    is left untouched). Thin wrapper over :func:`complete_qwen_usage` that drops
    the token usage.
    """
    content, _ = await complete_qwen_usage(
        messages, system_prompt,
        temperature=temperature, max_tokens=max_tokens,
        user_id=user_id, think=think,
    )
    return content
