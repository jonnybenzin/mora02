"""High-level generation API: turns user prompts into Asset lists.

Wraps builders + client + extract into the two pilot-facing entrypoints:
generate_images and generate_video.
"""

import random
from pathlib import Path
from typing import Optional

from mora02_core._common import get_logger
from mora02_core.assets import Asset
from mora02_core.comfyui.builders import build_video_workflow, build_workflow
from mora02_core.comfyui.client import (
    extract_error,
    extract_filenames,
    extract_video_filenames,
    poll_completion,
    queue_prompt,
)
from mora02_core.comfyui.registry import get_flow_info, load_registry, resolve_flow

_log = get_logger("mora02_core.comfyui.api")


def _image_asset(filename: str, variant: int) -> Asset:
    return Asset(
        id=filename,
        type="image",
        path=Path("/output/comfyui-wip") / filename,
        metadata={"url": f"/comfyui/wip/{filename}", "variant": variant},
    )


def _video_asset(filename: str) -> Asset:
    return Asset(
        id=filename,
        type="video",
        path=Path("/output/comfyui-wip") / filename,
        metadata={"url": f"/comfyui/wip/{filename}"},
    )


async def generate_images(
    prompt: str,
    flow: str = "photo",
    batch_size: Optional[int] = None,
    format: Optional[str] = None,
    cfg: Optional[float] = None,
    steps: Optional[int] = None,
    seed: Optional[int] = None,
    upscale: bool = False,
    facedetail: bool = False,
    testrun: bool = False,
    style_images: Optional[list[str]] = None,
    style_weight: float = 0.7,
    style_type: str = "style transfer",
    *,
    user_id: str = "default",
) -> dict:
    """Build → queue → poll → extract → wrap as Assets.

    API flows (Gemini/GPT/Flux) sometimes emit a <5 KB placeholder when the
    upstream provider 5xx's. We treat that as failure: empty assets list +
    explicit error string, so the UI doesn't show a black 64×64 thumbnail
    and cost tracking skips it.
    """
    flow = resolve_flow(flow)
    flow_info = get_flow_info(flow)
    actual_seed = seed or random.randint(0, 2**31 - 1)
    _log.info(
        "generate_images user=%s flow=%s batch=%s seed=%d",
        user_id, flow, batch_size, actual_seed,
    )
    workflow = build_workflow(
        prompt,
        flow=flow,
        seed=actual_seed,
        batch_size=batch_size,
        format=format,
        cfg=cfg,
        steps=steps,
        upscale=upscale,
        facedetail=facedetail,
        testrun=testrun,
        style_images=style_images,
        style_weight=style_weight,
        style_type=style_type,
    )
    timeout = 120 if flow == "sd15" else 300
    prompt_id = await queue_prompt(workflow, user_id=user_id)
    history = await poll_completion(prompt_id, timeout=timeout, user_id=user_id)
    filenames = extract_filenames(history)

    flow_config = load_registry()["flows"][flow]
    if flow_config.get("type") == "api" and filenames:
        # Filter out placeholder thumbnails from failed API calls
        valid = []
        for fname in filenames:
            for base in ("/output/comfyui-wip", "/images/wip"):
                p = Path(base) / fname
                if p.exists():
                    if p.stat().st_size >= 5000:
                        valid.append(fname)
                    break
        if not valid:
            return {
                "subtype": "image_variants",
                "prompt": prompt,
                "flow": flow,
                "flow_name": flow_info["name"],
                "seed": actual_seed,
                "prompt_id": prompt_id,
                "assets": [],
                "count": 0,
                "error": extract_error(history) or (
                    f"{flow_info['name']} lieferte kein gültiges Bild — "
                    f"externe API vermutlich nicht verfügbar (z.B. Google 503). "
                    f"Nichts berechnet."
                ),
            }
        filenames = valid

    assets = [_image_asset(f, idx + 1) for idx, f in enumerate(filenames)]
    result = {
        "subtype": "image_variants",
        "prompt": prompt,
        "flow": flow,
        "flow_name": flow_info["name"],
        "seed": actual_seed,
        "prompt_id": prompt_id,
        "assets": assets,
        "count": len(assets),
    }
    if not assets:
        result["error"] = extract_error(history) or (
            "Keine Bilder erzeugt — ComfyUI lieferte keinen Output."
        )
    return result


async def generate_video(
    prompt: str,
    flow: str = "wan-t2v",
    format: Optional[str] = None,
    steps: Optional[int] = None,
    seed: Optional[int] = None,
    length: Optional[int] = None,
    fps: Optional[int] = None,
    start_image: Optional[str] = None,
    end_image: Optional[str] = None,
    *,
    user_id: str = "default",
) -> dict:
    flow = resolve_flow(flow)
    flow_info = get_flow_info(flow)
    actual_seed = seed or random.randint(0, 2**31 - 1)
    _log.info("generate_video user=%s flow=%s seed=%d", user_id, flow, actual_seed)
    workflow = build_video_workflow(
        prompt,
        flow=flow,
        seed=actual_seed,
        format=format,
        steps=steps,
        length=length,
        fps=fps,
        start_image=start_image,
        end_image=end_image,
    )
    prompt_id = await queue_prompt(workflow, user_id=user_id)
    history = await poll_completion(prompt_id, timeout=600, user_id=user_id)
    filenames = extract_video_filenames(history)

    if not filenames:
        return {
            "subtype": "video_result",
            "assets": [],
            "error": extract_error(history) or "No video output found",
        }

    fname = filenames[0]
    return {
        "subtype": "video_result",
        "prompt": prompt,
        "flow": flow,
        "flow_name": flow_info["name"],
        "seed": actual_seed,
        "prompt_id": prompt_id,
        "assets": [_video_asset(fname)],
        "count": 1,
    }
