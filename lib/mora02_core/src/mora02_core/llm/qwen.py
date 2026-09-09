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
            if resp.status_code >= 400:
                # without this a 4xx/5xx streamed no "data:" lines at all and
                # the caller saw a model with nothing to say (review 5, B5)
                body = (await resp.aread()).decode("utf-8", "replace")[:200]
                yield {"type": "error", "error": f"llama.cpp answered {resp.status_code}: {body}"}
                return
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
    max_tokens: int | None = None,
    user_id: str = "default",
    think: bool = False,
) -> tuple[str, dict]:
    """Non-streaming completion that ALSO returns token usage.

    Same call as :func:`complete_qwen`, but returns ``(content, usage)`` where
    ``usage`` is ``{"tokens_in", "tokens_out", "model"}`` drawn from llama.cpp's
    response. Pipeline LLM steps use this to log per-step token counts; callers
    that only want the text use the :func:`complete_qwen` wrapper below.

    Qwen routes its chain-of-thought to a separate ``reasoning_content`` field;
    a long think can exhaust ``max_tokens`` before any ``content`` is emitted,
    yielding an empty answer. Value callers therefore run without it
    (``think=False``, the default). The switch is the chat template's own
    ``enable_thinking`` argument, passed per request: the ``/no_think`` prompt
    suffix this used to send was honoured by Qwen3 and is ignored by Qwen3.6,
    which thought for 256 tokens regardless and was cut off mid-label (measured
    2026-09-05 against the live server: 256 tokens and ``length`` with the
    suffix, 4 tokens and ``stop`` with the argument).

    No fallback to ``reasoning_content`` when ``content`` is empty: that handed
    a truncated train of thought to callers as if it were the answer, and one
    of them read a half-written label off its tail.
    """
    _log.debug("complete_qwen user=%s msgs=%d max_tokens=%s think=%s",
               user_id, len(messages), max_tokens, think)
    payload = {
        "model": "local",
        "messages": [{"role": "system", "content": system_prompt}] + messages,
        "stream": False,
        "temperature": temperature,
        "chat_template_kwargs": {"enable_thinking": think},
    }
    # No ceiling unless the caller asks for one. A fixed default turns "write a
    # 500 word story" into a sentence that breaks off mid-word: llama.cpp simply
    # stops counting. Without it the model ends where the answer ends, and
    # finish_reason says which of the two happened.
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            MODELS["qwen"]["endpoint"],
            json=payload, headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
    choice = data["choices"][0]
    message = choice["message"]
    content = (message.get("content") or "").strip()
    usage_raw = data.get("usage") or {}
    usage = {
        "tokens_in": usage_raw.get("prompt_tokens"),
        "tokens_out": usage_raw.get("completion_tokens"),
        "model": data.get("model"),  # llama.cpp echoes the served model name
        # "stop" = the model finished; "length" = it hit a ceiling and was cut.
        "finish_reason": choice.get("finish_reason"),
    }
    return content, usage


async def complete_qwen(
    messages: list[dict],
    system_prompt: str,
    *,
    temperature: float = 0.7,
    max_tokens: int | None = None,
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
