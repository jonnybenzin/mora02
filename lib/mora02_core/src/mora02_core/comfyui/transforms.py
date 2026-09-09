"""Image-transform endpoints: expand (outpaint) and upscale.

Both follow the same shape: take an image URL from the pilot, upload it
to ComfyUI's input dir, run a specialized workflow, return Assets.
"""

import copy
import random
from pathlib import Path
from typing import Optional

import httpx

from mora02_core._common import get_logger, segment_problem
from mora02_core.assets import Asset
from mora02_core.comfyui._config import COMFYUI_URL
from mora02_core.comfyui.client import (
    extract_filenames,
    poll_completion,
    queue_prompt,
)
from mora02_core.comfyui.builders import stamp_output_prefix
from mora02_core.comfyui.registry import load_registry, load_workflow
# ceiling for an image fetched from the asset server on the way into ComfyUI
MAX_SOURCE_IMAGE_BYTES = 50 * 1024 * 1024

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
    # Only the stack's own assets are sources: a path under the asset server.
    # A remote URL here was a readable SSRF - the response landed in ComfyUI's
    # input directory, viewable via /view (review 5, A5).
    if not image_url.startswith("/"):
        raise ValueError("image source must be a path on the asset server, not a URL")
    filename = Path(image_url).name
    problem = segment_problem(filename)
    if problem:
        raise ValueError(f"image name {problem}")
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
            download_url = f"http://nginx-images:80{image_url}"
            resp = await client.get(download_url)
            if resp.status_code != 200:
                raise Exception(
                    f"Failed to download image: {resp.status_code} (tried {download_url})"
                )
            if len(resp.content) > MAX_SOURCE_IMAGE_BYTES:
                raise ValueError("image source larger than the 50 MB ceiling")
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
    wf = stamp_output_prefix(copy.deepcopy(load_workflow(flow)))

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
    wf = stamp_output_prefix(copy.deepcopy(load_workflow(flow)))

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


async def edit_image(
    image_url: str,
    prompt: str,
    *,
    flow: str = "nanban",
    image_format: Optional[str] = None,
    temperature: Optional[float] = None,
    user_id: str = "default",
) -> dict:
    """Edit an existing image from an instruction ("put a blue hat on the rabbit").

    Not a diffusion img2img: the Gemini image models take the source picture plus
    an instruction and answer with a new picture. So there is no denoise strength
    and no seed to fix — the dials a diffusion flow would offer do not exist here,
    and pretending otherwise would only produce parameters that are silently
    ignored.

    ``flow`` is the user-facing generate flow ("nanban" / "nanban-pro"); the
    matching ``-edit`` variant is what actually runs. Keeping them as separate
    registry entries means the generate flows are untouched by editing.
    """
    edit_flow = flow if flow.endswith("-edit") else f"{flow}-edit"
    registry = load_registry()
    flow_config = registry["flows"].get(edit_flow)
    if flow_config is None:
        available = sorted(
            k[: -len("-edit")] for k in registry["flows"] if k.endswith("-edit")
        )
        raise ValueError(
            f"no editing flow for {flow!r} — available: {', '.join(available)}"
        )

    _log.info("edit user=%s flow=%s src=%s", user_id, edit_flow, image_url)
    comfyui_filename = await upload_image_url_to_comfyui(image_url)

    node_map = flow_config.get("node_map", {})
    wf = stamp_output_prefix(copy.deepcopy(load_workflow(edit_flow)))

    nm = node_map["image"]
    wf[nm["node"]]["inputs"][nm["field"]] = comfyui_filename
    nm = node_map["prompt"]
    wf[nm["node"]]["inputs"][nm["field"]] = prompt
    if image_format and "aspect_ratio" in node_map:
        aspect = flow_config.get("format_to_aspect", {}).get(image_format)
        if aspect:
            nm = node_map["aspect_ratio"]
            wf[nm["node"]]["inputs"][nm["field"]] = aspect
    if temperature is not None and "cfg" in node_map:
        # The registry maps "cfg" onto the node's temperature field for these flows.
        cap = float(flow_config.get("cfg_max", 2.0))
        nm = node_map["cfg"]
        wf[nm["node"]]["inputs"][nm["field"]] = max(0.0, min(cap, float(temperature)))

    prompt_id = await queue_prompt(wf, user_id=user_id)
    history = await poll_completion(prompt_id, timeout=300, user_id=user_id)
    filenames = extract_filenames(history)
    assets = [_asset_for(f) for f in filenames]

    return {
        "subtype": "edit_result",
        "source_image": image_url,
        "flow": edit_flow,
        "flow_name": flow_config.get("name"),
        "prompt": prompt,
        "cost_usd": flow_config.get("cost_per_image"),
        "assets": assets,
    }


# Human-facing matting model names -> what the rembg node expects. The node's own
# labels carry a description after the colon ("u2net: general purpose"), which is
# not something a pipeline author should have to type.
_CUTOUT_MODELS = {
    "isnet": "isnet-general-use: general purpose",
    "u2net": "u2net: general purpose",
    "human": "u2net_human_seg: human segmentation",
    "anime": "isnet-anime: anime illustrations",
    "silueta": "silueta: very small u2net",
}


async def cutout_image(
    image_url: str,
    *,
    model: str = "isnet",
    device: str = "CUDA",
    user_id: str = "default",
) -> dict:
    """Cut the subject out of an image and return a PNG with a real alpha channel.

    Two things decide whether the result has the grey halo that makes a cutout
    look pasted on. The matte comes from the matting model, but the COLOUR must
    come from the untouched original: the remover hands back premultiplied
    pixels, and storing those as a straight-alpha PNG makes every viewer darken
    the soft edge a second time. The workflow therefore joins the original image
    with the matte rather than saving the remover's own output.

    What remains after that is not fixable here: a pixel that is half subject and
    half background genuinely contains both colours. That residue is why a
    cutout against a strongly coloured background keeps a faint tint.

    ``model`` picks the matting model; ``"inspyrenet"`` switches to the finer
    (and slower) InSPyReNet flow, which needs the ``transparent-background``
    package in the ComfyUI image.
    """
    pro = model == "inspyrenet"
    flow = "cutout-pro" if pro else "cutout"
    if not pro and model not in _CUTOUT_MODELS:
        raise ValueError(
            f"unknown cutout model {model!r} — available: "
            + ", ".join(sorted(_CUTOUT_MODELS)) + ", inspyrenet"
        )

    registry = load_registry()
    flow_config = registry["flows"][flow]
    node_map = flow_config.get("node_map", {})
    _log.info("cutout user=%s flow=%s model=%s src=%s", user_id, flow, model, image_url)

    comfyui_filename = await upload_image_url_to_comfyui(image_url)
    wf = stamp_output_prefix(copy.deepcopy(load_workflow(flow)))
    nm = node_map["image"]
    wf[nm["node"]]["inputs"][nm["field"]] = comfyui_filename
    if not pro:
        nm = node_map["model"]
        wf[nm["node"]]["inputs"][nm["field"]] = _CUTOUT_MODELS[model]
        nm = node_map["device"]
        wf[nm["node"]]["inputs"][nm["field"]] = device

    prompt_id = await queue_prompt(wf, user_id=user_id)
    history = await poll_completion(prompt_id, timeout=300, user_id=user_id)
    filenames = extract_filenames(history)
    assets = [_asset_for(f) for f in filenames]

    return {
        "subtype": "cutout_result",
        "source_image": image_url,
        "flow": flow,
        "flow_name": flow_config.get("name"),
        "model": model,
        "assets": assets,
    }


async def erase_image(
    image_url: str,
    *,
    prompt: str = "",
    model: str = "isnet",
    grow: int = 90,
    seed: int | None = None,
    steps: int | None = None,
    user_id: str = "default",
) -> dict:
    """Remove the subject from an image and paint the scene back in behind it.

    The mirror image of :func:`cutout_image`: the same matte, used the other way
    round. There it decided what to KEEP, here it marks what to REPLACE — so the
    two together split one picture into a foreground layer with alpha and a
    complete background, which is what a parallax animation needs.

    The matte is deliberately grown before filling. One that stops exactly at the
    fur leaves a rim of subject pixels standing, and a fill model will happily
    build them into the new background — a ghost outline that is far more
    noticeable than a slightly larger hole.
    """
    flow = "erase"
    registry = load_registry()
    flow_config = registry["flows"][flow]
    node_map = flow_config.get("node_map", {})
    actual_seed = seed if seed is not None else random.randint(0, 2**31 - 1)
    _log.info("erase user=%s model=%s grow=%d src=%s", user_id, model, grow, image_url)

    comfyui_filename = await upload_image_url_to_comfyui(image_url)
    wf = stamp_output_prefix(copy.deepcopy(load_workflow(flow)))

    def put(key, value):
        nm = node_map.get(key)
        if nm and nm["node"] in wf:
            wf[nm["node"]]["inputs"][nm["field"]] = value

    put("image", comfyui_filename)
    put("seed", actual_seed)
    put("grow", int(grow))
    if model not in _CUTOUT_MODELS:
        raise ValueError(
            f"unknown matting model {model!r} — available: "
            + ", ".join(sorted(_CUTOUT_MODELS))
        )
    put("model", _CUTOUT_MODELS[model])
    if prompt:
        put("prompt", prompt)
    if steps:
        put("steps", int(steps))

    prompt_id = await queue_prompt(wf, user_id=user_id)
    history = await poll_completion(prompt_id, timeout=600, user_id=user_id)
    filenames = extract_filenames(history)
    assets = [_asset_for(f) for f in filenames]

    return {
        "subtype": "erase_result",
        "source_image": image_url,
        "flow": flow,
        "flow_name": flow_config.get("name"),
        "seed": actual_seed,
        "grow": grow,
        "assets": assets,
    }


async def facefix_image(
    image_url: str,
    *,
    prompt: str = "",
    denoise: float | None = None,
    seed: int | None = None,
    steps: int | None = None,
    user_id: str = "default",
) -> dict:
    """Re-render the faces in an image at higher detail, leaving the rest alone.

    A detector finds each face, and only those crops are sampled again — which is
    why small faces in a wide shot come out sharp without touching the
    composition. Deliberately its own flow rather than a switch inside the image
    flows: there the branch hangs off the upscale chain, so it silently does
    nothing whenever upscaling is off.

    ``denoise`` is the dial that matters. Low values refine, high values invent —
    past roughly 0.6 the face stops being the same person.
    """
    flow = "facefix"
    registry = load_registry()
    flow_config = registry["flows"][flow]
    node_map = flow_config.get("node_map", {})
    actual_seed = seed if seed is not None else random.randint(0, 2**31 - 1)
    _log.info("facefix user=%s src=%s", user_id, image_url)

    comfyui_filename = await upload_image_url_to_comfyui(image_url)
    wf = stamp_output_prefix(copy.deepcopy(load_workflow(flow)))

    def put(key, value):
        nm = node_map.get(key)
        if nm and nm["node"] in wf:
            wf[nm["node"]]["inputs"][nm["field"]] = value

    put("image", comfyui_filename)
    put("seed", actual_seed)
    if prompt:
        put("prompt", prompt)
    if denoise is not None:
        put("denoise", float(denoise))
    if steps:
        put("steps", int(steps))

    prompt_id = await queue_prompt(wf, user_id=user_id)
    history = await poll_completion(prompt_id, timeout=600, user_id=user_id)
    filenames = extract_filenames(history)
    assets = [_asset_for(f) for f in filenames]

    return {
        "subtype": "facefix_result",
        "source_image": image_url,
        "flow": flow,
        "flow_name": flow_config.get("name"),
        "seed": actual_seed,
        "assets": assets,
    }
