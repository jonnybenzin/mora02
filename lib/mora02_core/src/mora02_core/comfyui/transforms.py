"""Image-transform endpoints: expand (outpaint) and upscale.

Both follow the same shape: take an image URL from the pilot, upload it
to ComfyUI's input dir, run a specialized workflow, return Assets.
"""

import copy
import random
from pathlib import Path
from typing import Optional

import httpx

from mora02_core._common import get_logger
from mora02_core.assets import Asset
from mora02_core.comfyui._config import COMFYUI_URL
from mora02_core.comfyui.client import (
    extract_filenames,
    poll_completion,
    queue_prompt,
)
from mora02_core.comfyui.registry import load_registry, load_workflow

_log = get_logger("mora02_core.comfyui.transforms")


def _wip_path(filename: str) -> Path:
    """Map an output filename to its in-container path on the wip mount.

    Container layout: /output/comfyui-wip/<filename> (writable) or
    /images/wip/<filename> (read-only). We return the writable one for
    Asset.path; consumers compute UI URLs from metadata.
    """
    return Path("/output/comfyui-wip") / filename


def _asset_for(filename: str) -> Asset:
    return Asset(
        id=filename,
        type="image",
        path=_wip_path(filename),
        metadata={"url": f"/comfyui/wip/{filename}"},
    )


async def upload_image_url_to_comfyui(image_url: str) -> str:
    """Read an image from the pilot's local volume (or via HTTP) and POST it
    to ComfyUI's /upload/image as a deterministic 'expand_' prefixed name."""
    filename = Path(image_url).name
    local_path: Optional[Path] = None
    if "/comfyui/wip/" in image_url:
        local_path = Path("/images/wip") / filename
    elif "/output/" in image_url:
        local_path = Path("/output/comfyui-wip") / filename

    dest_name = f"expand_{filename}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        if local_path and local_path.exists():
            image_data = local_path.read_bytes()
        else:
            download_url = (
                f"http://nginx-images:80{image_url}"
                if image_url.startswith("/") else image_url
            )
            resp = await client.get(download_url)
            if resp.status_code != 200:
                raise Exception(
                    f"Failed to download image: {resp.status_code} (tried {download_url})"
                )
            image_data = resp.content
        upload_resp = await client.post(
            f"{COMFYUI_URL}/upload/image",
            files={"image": (dest_name, image_data, "image/png")},
            data={"overwrite": "true"},
        )
        if upload_resp.status_code == 200:
            return upload_resp.json().get("name", dest_name)
    return dest_name


async def expand_image(
    image_url: str,
    prompt: str = "",
    target_size: int = 1920,
    seed: Optional[int] = None,
    steps: Optional[int] = None,
    feathering: Optional[int] = None,
    *,
    user_id: str = "default",
) -> dict:
    """Outpaint an image to target_size x target_size.

    Source size is assumed square 1024 → padding = (target-1024)/2 per side.
    Returns a dict with subtype + assets (list[Asset]).
    """
    _log.info("expand user=%s target=%dx%d", user_id, target_size, target_size)
    actual_seed = seed or random.randint(0, 2**31 - 1)
    comfyui_filename = await upload_image_url_to_comfyui(image_url)

    source_size = 1024
    pad = max(0, (target_size - source_size) // 2)

    flow = "expand"
    registry = load_registry()
    flow_config = registry["flows"][flow]
    node_map = flow_config.get("node_map", {})
    wf = copy.deepcopy(load_workflow(flow))

    if "image" in node_map:
        nm = node_map["image"]
        wf[nm["node"]]["inputs"][nm["field"]] = comfyui_filename
    if "prompt" in node_map:
        nm = node_map["prompt"]
        default_prompt = (
            "extend the background naturally, same style, same lighting, "
            "same scene, seamless continuation, high quality"
        )
        wf[nm["node"]]["inputs"][nm["field"]] = prompt or default_prompt
    if "seed" in node_map:
        nm = node_map["seed"]
        wf[nm["node"]]["inputs"][nm["field"]] = actual_seed
    for pad_key in ["pad_left", "pad_top", "pad_right", "pad_bottom"]:
        if pad_key in node_map:
            nm = node_map[pad_key]
            wf[nm["node"]]["inputs"][nm["field"]] = pad
    if steps and "steps" in node_map:
        nm = node_map["steps"]
        wf[nm["node"]]["inputs"][nm["field"]] = steps
    if feathering is not None and "feathering" in node_map:
        nm = node_map["feathering"]
        wf[nm["node"]]["inputs"][nm["field"]] = feathering

    prompt_id = await queue_prompt(wf, user_id=user_id)
    history = await poll_completion(prompt_id, timeout=300, user_id=user_id)
    filenames = extract_filenames(history)
    assets = [_asset_for(f) for f in filenames]

    return {
        "subtype": "expand_result",
        "source_image": image_url,
        "prompt": prompt,
        "seed": actual_seed,
        "target": f"{target_size}x{target_size}",
        "prompt_id": prompt_id,
        "assets": assets,
        "count": len(assets),
    }


async def upscale_image(
    image_url: str,
    factor: float = 2.0,
    prompt: str = "",
    denoise: Optional[float] = None,
    seed: Optional[int] = None,
    steps: Optional[int] = None,
    cfg: Optional[float] = None,
    *,
    user_id: str = "default",
) -> dict:
    """Hybrid SDXL-Tile upscaler (Juggernaut + 4x-UltraSharp + UltimateSDUpscale).

    factor: 1.5–4.0; denoise: 0.05–0.5 (default 0.2 sweet-spot).
    """
    _log.info("upscale user=%s factor=%s", user_id, factor)
    actual_seed = seed or random.randint(0, 2**31 - 1)
    factor = max(1.5, min(4.0, float(factor)))
    comfyui_filename = await upload_image_url_to_comfyui(image_url)

    flow = "upscale"
    registry = load_registry()
    flow_config = registry["flows"][flow]
    node_map = flow_config.get("node_map", {})
    suffix = flow_config.get("prompt_suffix", "")
    default_negative = flow_config.get("negative", "")
    wf = copy.deepcopy(load_workflow(flow))

    if "image" in node_map:
        nm = node_map["image"]
        wf[nm["node"]]["inputs"][nm["field"]] = comfyui_filename
    if "prompt" in node_map:
        nm = node_map["prompt"]
        user_part = (prompt or "").strip()
        full_prompt = (user_part + suffix) if user_part else suffix.lstrip(", ")
        wf[nm["node"]]["inputs"][nm["field"]] = full_prompt
    if "negative" in node_map:
        nm = node_map["negative"]
        wf[nm["node"]]["inputs"][nm["field"]] = default_negative
    if "seed" in node_map:
        nm = node_map["seed"]
        wf[nm["node"]]["inputs"][nm["field"]] = actual_seed
    if "factor" in node_map:
        nm = node_map["factor"]
        wf[nm["node"]]["inputs"][nm["field"]] = float(factor)
    if denoise is not None and "denoise" in node_map:
        nm = node_map["denoise"]
        wf[nm["node"]]["inputs"][nm["field"]] = max(0.05, min(0.5, float(denoise)))
    if steps is not None and "steps" in node_map:
        nm = node_map["steps"]
        wf[nm["node"]]["inputs"][nm["field"]] = max(8, min(40, int(steps)))
    if cfg is not None and "cfg" in node_map:
        nm = node_map["cfg"]
        wf[nm["node"]]["inputs"][nm["field"]] = max(1.0, min(12.0, float(cfg)))

    prompt_id = await queue_prompt(wf, user_id=user_id)
    history = await poll_completion(prompt_id, timeout=600, user_id=user_id)
    filenames = extract_filenames(history)
    assets = [_asset_for(f) for f in filenames]

    return {
        "subtype": "upscale_result",
        "source_image": image_url,
        "prompt": prompt,
        "seed": actual_seed,
        "factor": factor,
        "denoise": denoise if denoise is not None else 0.2,
        "prompt_id": prompt_id,
        "assets": assets,
        "count": len(assets),
    }
