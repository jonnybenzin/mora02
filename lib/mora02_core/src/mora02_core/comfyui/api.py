"""High-level generation API: turns user prompts into Asset lists.

Wraps builders + client + extract into the two pilot-facing entrypoints:
generate_images and generate_video.
"""

import random
from pathlib import Path
from typing import Optional

from mora02_core._common import get_logger
from mora02_core.assets import Asset
from mora02_core.comfyui.builders import (
    build_music_workflow,
    build_video_workflow,
    build_workflow,
)
from mora02_core.comfyui.client import (
    extract_audio_filenames,
    extract_error,
    extract_filenames,
    extract_video_filenames,
    poll_completion,
    queue_prompt,
)
from mora02_core.comfyui.registry import get_flow_info, load_registry, resolve_flow

_log = get_logger("mora02_core.comfyui.api")

# The same host directory (ComfyUI's output) is mounted under a different name in
# each service — /images/wip and /output/comfyui-wip in pilot, /comfyui-wip in
# script-runner and nginx-images. Every name this library might run under.
_WIP_BASES = ("/output/comfyui-wip", "/images/wip", "/comfyui-wip")


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


def _audio_asset(filename: str) -> Asset:
    return Asset(
        id=filename,
        type="audio",
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
        # A failed API call still leaves a file behind: the custom node writes a
        # tiny placeholder thumbnail. Size is the only way to tell it from a real
        # result, so anything under 5 KB counts as a failure.
        valid = []
        for fname in filenames:
            for base in _WIP_BASES:
                candidate = Path(base) / fname
                if candidate.exists():
                    if candidate.stat().st_size >= 5000:
                        valid.append(fname)
                    break
            else:
                # Not visible from THIS container. ComfyUI wrote the file, we just
                # cannot look at it — the same host directory is mounted under a
                # different name in every service. Not seeing a file is not the
                # same as the API failing, so accept it instead of inventing an
                # outage: reporting a Google 503 that never happened sends the
                # search in exactly the wrong direction.
                _log.warning(
                    "comfyui output %s not readable from this container "
                    "(checked %s) — skipping the placeholder check",
                    fname, ", ".join(_WIP_BASES),
                )
                valid.append(fname)
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
    # Paid API flows carry a per-image price in the registry; local flows don't
    # (cost 0.0). Charge only for images actually produced (count), so a failed
    # API call billed nothing.
    cost_per_image = flow_config.get("cost_per_image", 0.0)
    result = {
        "subtype": "image_variants",
        "prompt": prompt,
        "flow": flow,
        "flow_name": flow_info["name"],
        "seed": actual_seed,
        "prompt_id": prompt_id,
        "assets": assets,
        "count": len(assets),
        "cost_usd": round(cost_per_image * len(assets), 6),
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


async def generate_music(
    tags: str,
    flow: str = "ace-music",
    lyrics: str = "",
    seed: Optional[int] = None,
    duration: Optional[int] = None,
    steps: Optional[int] = None,
    bpm: Optional[int] = None,
    key: Optional[str] = None,
    time_signature: Optional[str] = None,
    language: Optional[str] = None,
    cfg_scale: Optional[float] = None,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    top_k: Optional[int] = None,
    min_p: Optional[float] = None,
    ref_audio: Optional[str] = None,
    *,
    user_id: str = "default",
) -> dict:
    flow = resolve_flow(flow)
    flow_info = get_flow_info(flow)
    actual_seed = seed or random.randint(0, 2**31 - 1)
    _log.info("generate_music user=%s flow=%s seed=%d dur=%s", user_id, flow, actual_seed, duration)
    workflow = build_music_workflow(
        tags,
        flow=flow,
        lyrics=lyrics,
        seed=actual_seed,
        duration=duration,
        steps=steps,
        bpm=bpm,
        key=key,
        time_signature=time_signature,
        language=language,
        cfg_scale=cfg_scale,
        temperature=temperature,
        top_p=top_p,
        top_k=top_k,
        min_p=min_p,
        ref_audio=ref_audio,
    )
    prompt_id = await queue_prompt(workflow, user_id=user_id)
    history = await poll_completion(prompt_id, timeout=600, user_id=user_id)
    filenames = extract_audio_filenames(history)

    if not filenames:
        return {
            "subtype": "music_result",
            "assets": [],
            "error": extract_error(history) or "No audio output found",
        }

    fname = filenames[0]
    return {
        "subtype": "music_result",
        "tags": tags,
        "flow": flow,
        "flow_name": flow_info["name"],
        "seed": actual_seed,
        "prompt_id": prompt_id,
        "assets": [_audio_asset(fname)],
        "count": 1,
    }
