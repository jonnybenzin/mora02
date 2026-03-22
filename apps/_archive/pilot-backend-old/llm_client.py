import httpx
import json
from typing import AsyncGenerator, Optional
from config import settings, MODELS


async def stream_qwen(messages: list[dict], system_prompt: str,
                       temperature: float = 0.7, max_tokens: int = 4096) -> AsyncGenerator[dict, None]:
    payload = {
        "model": "Qwen3-14B-Q4_K_M",
        "messages": [{"role": "system", "content": system_prompt}] + messages,
        "stream": True,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream("POST", MODELS["qwen"]["endpoint"],
                                  json=payload,
                                  headers={"Content-Type": "application/json"}) as resp:
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


async def stream_claude(messages: list[dict], system_prompt: str,
                         model_key: str = "sonnet",
                         image_data: Optional[dict] = None,
                         temperature: float = 0.7,
                         max_tokens: int = 4096) -> AsyncGenerator[dict, None]:
    import anthropic
    model_config = MODELS[model_key]
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

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


async def stream_llm(messages: list[dict], system_prompt: str,
                      model_key: str = "qwen",
                      image_data: Optional[dict] = None,
                      temperature: float = 0.7,
                      max_tokens: int = 4096) -> AsyncGenerator[dict, None]:
    if model_key == "qwen":
        async for chunk in stream_qwen(messages, system_prompt, temperature, max_tokens):
            yield chunk
    else:
        async for chunk in stream_claude(messages, system_prompt, model_key, image_data, temperature, max_tokens):
            yield chunk
