"""Low-level ComfyUI HTTP client: queue, poll, extract.

Translates the recurring VRAM phantom-OOM into a user-actionable hint (see
[[comfyui-phantom-oom]] in the project notes).
"""

import asyncio
from typing import Optional

import httpx

from mora02_core._common import get_logger
from mora02_core.comfyui._config import COMFYUI_URL

_log = get_logger("mora02_core.comfyui.client")


async def queue_prompt(workflow: dict, *, user_id: str = "default") -> str:
    """POST a workflow to /prompt. Returns the prompt_id ComfyUI assigned."""
    _log.debug("queue_prompt user=%s nodes=%d", user_id, len(workflow))
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(f"{COMFYUI_URL}/prompt", json={"prompt": workflow})
        if resp.status_code == 200:
            data = resp.json()
            if "prompt_id" in data:
                return data["prompt_id"]
            raise Exception(f"ComfyUI error: {data.get('error', data)}")
        raise Exception(f"ComfyUI HTTP {resp.status_code}: {resp.text[:800]}")


async def poll_completion(
    prompt_id: str,
    timeout: int = 180,
    interval: float = 2.0,
    *,
    user_id: str = "default",
) -> dict:
    """Poll /history/<id> until ComfyUI reports completion or timeout."""
    elapsed = 0.0
    async with httpx.AsyncClient(timeout=10.0) as client:
        while elapsed < timeout:
            resp = await client.get(f"{COMFYUI_URL}/history/{prompt_id}")
            if resp.status_code == 200:
                data = resp.json()
                if prompt_id in data:
                    return data[prompt_id]
            await asyncio.sleep(interval)
            elapsed += interval
    raise TimeoutError(f"ComfyUI timed out after {timeout}s")


def extract_filenames(history: dict) -> list[str]:
    filenames = []
    outputs = history.get("outputs", {})
    for _node_id, node_output in outputs.items():
        for img in node_output.get("images", []):
            if img.get("type") == "output":
                filenames.append(img["filename"])
    return filenames


def extract_video_filenames(history: dict) -> list[str]:
    filenames = []
    outputs = history.get("outputs", {})
    for _node_id, node_output in outputs.items():
        # ComfyUI returns video files under "images" with animated=true
        if node_output.get("animated"):
            for item in node_output.get("images", []):
                if item.get("type") == "output":
                    subfolder = item.get("subfolder", "")
                    fname = item["filename"]
                    filenames.append(f"{subfolder}/{fname}" if subfolder else fname)
    return filenames


def extract_error(history: dict) -> Optional[str]:
    """Pull a human-readable failure reason out of a ComfyUI history entry."""
    status = history.get("status", {})
    if status.get("status_str") != "error":
        return None
    for m in status.get("messages", []):
        if m[0] != "execution_error":
            continue
        info = m[1]
        msg = (info.get("exception_message") or "")
        etype = (info.get("exception_type") or "")
        node = info.get("node_type") or info.get("node_id") or "?"
        if "out of memory" in msg.lower() or "OutOfMemoryError" in etype:
            return ("ComfyUI VRAM voll (Phantom-OOM). Im Dashboard auf "
                    "'FREE GPU MEMORY' klicken, dann erneut generieren.")
        short = msg.strip().split("\n")[0][:200]
        return f"ComfyUI-Fehler in Node {node}: {short}"
    return "ComfyUI-Job fehlgeschlagen (kein Output)."
