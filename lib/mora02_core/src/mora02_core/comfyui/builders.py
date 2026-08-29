"""Workflow builders: pour user params into a workflow JSON via node_map.

Each flow in the registry declares a `node_map` mapping logical params
(prompt, seed, batch, width, height, ...) to (node_id, field_name) pairs.
This module reads that mapping and patches the workflow accordingly.
"""

import copy
import random
from datetime import datetime
from typing import Optional

from mora02_core._common import get_logger
from mora02_core.comfyui.registry import load_registry, load_workflow, resolve_flow
from mora02_core.comfyui.style_injection import IPADAPTER_FLOWS, inject_ipadapter_nodes

_log = get_logger("mora02_core.comfyui.builders")

FORMATS = {
    "portrait":  (768, 1152),
    "landscape": (1152, 768),
    "square":    (1024, 1024),
}

# Smaller dimensions for local SD/XL flows when --testrun is set (~3x faster)
FORMATS_TEST = {
    "portrait":  (512, 768),
    "landscape": (768, 512),
    "square":    (704, 704),
}




# Every save node type ComfyUI writes through. A workflow only carries the ones
# it needs, so stamping them all is the same as stamping the one it has.
_SAVE_NODES = ("SaveImage", "SaveVideo", "SaveAudio", "SaveAudioMP3")


def stamp_output_prefix(wf: dict) -> dict:
    """Append YYMMDD-HHMM to every save node's filename_prefix, in place.

    Without it ComfyUI numbers per prefix from one, so a second run of the same
    flow collides with the first — "edit_00001_.png" is either overwritten or
    silently counts on from whatever is left in the directory. The timestamp is
    what makes an output belong to the run that made it.

    Applies to the workflow as loaded, so it must run for every flow — the ones
    built by :func:`build_workflow` as well as the transform flows that load
    their workflow directly.
    """
    ts = datetime.now().strftime("%y%m%d-%H%M")
    for _nid, node in wf.items():
        if (node.get("class_type") in _SAVE_NODES
                and "filename_prefix" in node.get("inputs", {})):
            node["inputs"]["filename_prefix"] = f"{node['inputs']['filename_prefix']}_{ts}"
    return wf

def parse_format(fmt: str) -> Optional[tuple[int, int]]:
    """Parse format string: 'portrait', '768x1152', etc."""
    if not fmt:
        return None
    fmt = fmt.lower().strip()
    if fmt in FORMATS:
        return FORMATS[fmt]
    for sep in ["x", "X", "×", "*"]:
        if sep in fmt:
            parts = fmt.split(sep)
            if len(parts) == 2:
                try:
                    w, h = int(parts[0].strip()), int(parts[1].strip())
                    if 256 <= w <= 2048 and 256 <= h <= 2048:
                        return (w, h)
                except ValueError:
                    pass
    return None


def build_workflow(
    prompt: str,
    flow: str = "photo",
    seed: Optional[int] = None,
    batch_size: Optional[int] = None,
    format: Optional[str] = None,
    cfg: Optional[float] = None,
    steps: Optional[int] = None,
    upscale: bool = False,
    facedetail: bool = False,
    testrun: bool = False,
    style_images: Optional[list[str]] = None,
    style_weight: float = 0.7,
    style_type: str = "style transfer",
) -> dict:
    flow = resolve_flow(flow)
    registry = load_registry()
    flow_config = registry["flows"][flow]
    node_map = flow_config.get("node_map", {})
    wf = copy.deepcopy(load_workflow(flow))

    # Prompt
    suffix = flow_config.get("prompt_suffix", "")
    full_prompt = prompt + suffix if suffix else prompt
    if "prompt" in node_map:
        pm = node_map["prompt"]
        if pm["node"] in wf:
            wf[pm["node"]]["inputs"][pm["field"]] = full_prompt

    # Negative
    negative = flow_config.get("negative", "")
    if "negative" in node_map and negative:
        nm = node_map["negative"]
        if nm["node"] in wf:
            wf[nm["node"]]["inputs"][nm["field"]] = negative

    # Seed
    actual_seed = seed or random.randint(0, 2**31 - 1)
    if "seed" in node_map:
        sm = node_map["seed"]
        if sm["node"] in wf:
            wf[sm["node"]]["inputs"][sm["field"]] = actual_seed

    # Batch
    max_batch = flow_config.get("max_batch", 4)
    effective = min(batch_size, max_batch) if batch_size else max_batch
    if "batch" in node_map:
        bm = node_map["batch"]
        if bm["node"] in wf:
            wf[bm["node"]]["inputs"][bm["field"]] = effective

    # Format → aspect ratio (for API flows: Nano Banana, Flux Ultra)
    if "aspect_ratio" in node_map:
        format_map = flow_config.get("format_to_aspect", {})
        fmt_key = (format or "square").lower().strip()
        ar = format_map.get(fmt_key, "1:1")
        am = node_map["aspect_ratio"]
        if am["node"] in wf:
            wf[am["node"]]["inputs"][am["field"]] = ar
        # Testrun → smaller image_size tier (Gemini: 4K/2K → 1K).
        # Flux Ultra has no image_size in node_map → testrun is a no-op there.
        if "image_size" in node_map:
            full_size = flow_config.get("image_size_full", "2K")
            siz = node_map["image_size"]
            if siz["node"] in wf:
                wf[siz["node"]]["inputs"][siz["field"]] = "1K" if testrun else full_size
    else:
        # Format → Width/Height (for local SD/XL flows)
        fmt_key = (format or "square").lower().strip()
        table = FORMATS_TEST if testrun else FORMATS
        dims = table.get(fmt_key) or parse_format(format)
        if dims:
            w, h = dims
            if "width" in node_map:
                wm = node_map["width"]
                if wm["node"] in wf:
                    wf[wm["node"]]["inputs"][wm["field"]] = w
            if "height" in node_map:
                hm = node_map["height"]
                if hm["node"] in wf:
                    wf[hm["node"]]["inputs"][hm["field"]] = h

    # CFG (clamped by cfg_max for API flows where cfg maps to temperature)
    if "cfg" in node_map:
        cfg_max = flow_config.get("cfg_max")
        if cfg is not None and cfg_max and float(cfg) > cfg_max:
            cfg = cfg_max
        # For API flows without seed: randomize temperature slightly to bust ComfyUI cache
        if cfg is None and cfg_max:
            cfg = round(random.uniform(0.8, cfg_max), 2)
        if cfg is not None:
            cm = node_map["cfg"]
            if cm["node"] in wf:
                wf[cm["node"]]["inputs"][cm["field"]] = float(cfg)

    # Steps
    if steps is not None and "steps" in node_map:
        sm2 = node_map["steps"]
        if sm2["node"] in wf:
            wf[sm2["node"]]["inputs"][sm2["field"]] = int(steps)

    # Upscale off → remove upscale nodes
    if not upscale:
        for nid in ["313", "314", "315", "326", "455"]:
            if nid in wf:
                del wf[nid]

    # FaceDetailer off → remove face nodes
    if not facedetail:
        for nid in ["462", "475", "478", "456"]:
            if nid in wf:
                del wf[nid]

    stamp_output_prefix(wf)

    # IP-Adapter style injection
    if style_images and flow in IPADAPTER_FLOWS:
        wf = inject_ipadapter_nodes(wf, style_images, weight=style_weight, weight_type=style_type)

    return wf


def build_video_workflow(
    prompt: str,
    flow: str = "wan-t2v",
    seed: Optional[int] = None,
    format: Optional[str] = None,
    steps: Optional[int] = None,
    length: Optional[int] = None,
    fps: Optional[int] = None,
    start_image: Optional[str] = None,
    end_image: Optional[str] = None,
) -> dict:
    flow = resolve_flow(flow)
    registry = load_registry()
    flow_config = registry["flows"][flow]
    node_map = flow_config.get("node_map", {})
    wf = copy.deepcopy(load_workflow(flow))

    if "prompt" in node_map:
        pm = node_map["prompt"]
        if pm["node"] in wf:
            wf[pm["node"]]["inputs"][pm["field"]] = prompt

    actual_seed = seed or random.randint(0, 2**31 - 1)
    if "seed" in node_map:
        sm = node_map["seed"]
        if sm["node"] in wf:
            wf[sm["node"]]["inputs"][sm["field"]] = actual_seed

    # Steps — WAN uses two samplers (high/low noise), both need the same steps
    if steps is not None:
        half = max(1, steps // 2)
        if "steps" in node_map:
            sm = node_map["steps"]
            if sm["node"] in wf:
                wf[sm["node"]]["inputs"][sm["field"]] = int(steps)
                wf[sm["node"]]["inputs"]["end_at_step"] = half
        if "steps2" in node_map:
            sm2 = node_map["steps2"]
            if sm2["node"] in wf:
                wf[sm2["node"]]["inputs"][sm2["field"]] = int(steps)
                wf[sm2["node"]]["inputs"]["start_at_step"] = half

    # Format
    dims = parse_format(format)
    if dims:
        w, h = dims
        if "width" in node_map:
            wm = node_map["width"]
            if wm["node"] in wf:
                wf[wm["node"]]["inputs"][wm["field"]] = w
        if "height" in node_map:
            hm = node_map["height"]
            if hm["node"] in wf:
                wf[hm["node"]]["inputs"][hm["field"]] = h

    if length is not None and "length" in node_map:
        lm = node_map["length"]
        if lm["node"] in wf:
            wf[lm["node"]]["inputs"][lm["field"]] = int(length)

    if fps is not None and "fps" in node_map:
        fm = node_map["fps"]
        if fm["node"] in wf:
            wf[fm["node"]]["inputs"][fm["field"]] = int(fps)

    if start_image and "start_image" in node_map:
        si = node_map["start_image"]
        if si["node"] in wf:
            wf[si["node"]]["inputs"][si["field"]] = start_image

    if end_image and "end_image" in node_map:
        ei = node_map["end_image"]
        if ei["node"] in wf:
            wf[ei["node"]]["inputs"][ei["field"]] = end_image

    stamp_output_prefix(wf)

    return wf


def build_music_workflow(
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
) -> dict:
    """Pour music params into the ACE-Step workflow via its node_map.

    Like build_video_workflow, but for the audio graph. Two params fan out to
    two nodes each — duration feeds both the empty-latent (seconds) and the text
    encoder (duration), and seed feeds both the text encoder and the sampler —
    so the registry declares them as *_latent/_text and *_text/_sampler pairs.
    An optional ref_audio adds the reference-timbre sub-graph and rewires the
    sampler's positive conditioning to it (mirrors the pilot music route).
    """
    flow = resolve_flow(flow)
    registry = load_registry()
    flow_config = registry["flows"][flow]
    node_map = flow_config.get("node_map", {})
    wf = copy.deepcopy(load_workflow(flow))

    def _patch(logical: str, value) -> None:
        if value is None or logical not in node_map:
            return
        m = node_map[logical]
        if m["node"] in wf:
            wf[m["node"]]["inputs"][m["field"]] = value

    _patch("tags", tags)
    _patch("lyrics", lyrics)
    _patch("key", key)
    _patch("language", language)
    _patch("time_signature", str(time_signature) if time_signature is not None else None)
    _patch("bpm", int(bpm) if bpm is not None else None)
    _patch("steps", int(steps) if steps is not None else None)
    _patch("cfg_scale", float(cfg_scale) if cfg_scale is not None else None)
    _patch("temperature", float(temperature) if temperature is not None else None)
    _patch("top_p", float(top_p) if top_p is not None else None)
    _patch("top_k", int(top_k) if top_k is not None else None)
    _patch("min_p", float(min_p) if min_p is not None else None)

    # Duration fans out to the latent length and the text encoder.
    if duration is not None:
        _patch("duration_latent", int(duration))
        _patch("duration_text", int(duration))

    # Seed fans out to the text encoder and the sampler (kept identical).
    actual_seed = seed or random.randint(0, 2**31 - 1)
    _patch("seed_text", actual_seed)
    _patch("seed_sampler", actual_seed)

    # Reference timbre: LoadAudio -> VAEEncodeAudio -> ReferenceTimbreAudio, then
    # point the sampler's positive conditioning at the reference-augmented one.
    if ref_audio:
        wf["11"] = {"class_type": "LoadAudio", "inputs": {"audio": ref_audio}}
        wf["12"] = {"class_type": "VAEEncodeAudio",
                    "inputs": {"audio": ["11", 0], "vae": ["1", 2]}}
        wf["13"] = {"class_type": "ReferenceTimbreAudio",
                    "inputs": {"conditioning": ["6", 0], "latent": ["12", 0]}}
        if "8" in wf:
            wf["8"]["inputs"]["positive"] = ["13", 0]

    stamp_output_prefix(wf)

    return wf
