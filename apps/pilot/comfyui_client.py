"""
Mora02 ComfyUI Client — File-based workflow system with node_map.
Supports: flow, format, cfg, steps, seed, batch, upscale, facedetail.
"""

import httpx
import json
import asyncio
import random
import copy
import shutil
from pathlib import Path
from datetime import datetime

COMFYUI_URL = "http://comfyui:8188"
COMFYUI_INPUT_DIR = Path("/comfyui-input")
WORKFLOWS_DIR = Path("/workflows")
STYLES_DIR = Path("/data/styles")
_registry_cache = None
_workflow_cache = {}

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"}

FORMATS = {
    "portrait":  (768, 1152),
    "landscape": (1152, 768),
    "square":    (1024, 1024),
}


def parse_format(fmt: str) -> tuple[int, int] | None:
    """Parse format string: 'portrait', '768x1152', etc."""
    if not fmt:
        return None
    fmt = fmt.lower().strip()
    if fmt in FORMATS:
        return FORMATS[fmt]
    # Try WxH parsing
    for sep in ['x', 'X', '×', '*']:
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


def load_registry(force=False) -> dict:
    global _registry_cache
    if _registry_cache is not None and not force:
        return _registry_cache
    reg_path = WORKFLOWS_DIR / "_registry.json"
    if not reg_path.exists():
        raise FileNotFoundError(f"Registry not found: {reg_path}")
    with open(reg_path) as f:
        _registry_cache = json.load(f)
    return _registry_cache


def load_workflow(flow_key: str) -> dict:
    if flow_key in _workflow_cache:
        return _workflow_cache[flow_key]
    registry = load_registry()
    flow_config = registry["flows"].get(flow_key)
    if not flow_config:
        raise ValueError(f"Unknown flow: {flow_key}")
    wf_path = WORKFLOWS_DIR / flow_config["file"]
    if not wf_path.exists():
        raise FileNotFoundError(f"Workflow not found: {wf_path}")
    with open(wf_path) as f:
        wf = json.load(f)
    _workflow_cache[flow_key] = wf
    return wf


def resolve_flow(name: str) -> str:
    name = name.lower().strip()
    registry = load_registry()
    flows = registry["flows"]
    if name in flows:
        return name
    for key, config in flows.items():
        if name in config.get("aliases", []):
            return key
    return registry.get("default_flow", "photo")


def get_flow_info(flow: str) -> dict:
    flow = resolve_flow(flow)
    registry = load_registry()
    config = registry["flows"][flow]
    return {
        "flow": flow,
        "name": config["name"],
        "max_batch": config.get("max_batch", 4),
        "needs_vram": config.get("needs_vram", False),
    }


def list_flows() -> list[dict]:
    registry = load_registry()
    return [{"flow": k, "name": v["name"], "max_batch": v.get("max_batch", 4),
             "needs_vram": v.get("needs_vram", False), "aliases": v.get("aliases", [])}
            for k, v in registry["flows"].items()]


def reload_flows():
    global _registry_cache, _workflow_cache
    _registry_cache = None
    _workflow_cache = {}
    load_registry(force=True)


# ============================================================
# IP-ADAPTER STYLE REFERENCE
# ============================================================

# Flows that support IP-Adapter injection (SDXL with Eff. Loader pattern)
IPADAPTER_FLOWS = {"photo", "concept", "epic"}


def prepare_style_images(source_path: str, count: int = 4) -> list[str]:
    """Select random images from a style pack folder and copy to ComfyUI input dir.

    Returns list of filenames (relative to ComfyUI input dir).
    """
    src = Path(source_path)
    if not src.is_dir():
        return []
    images = [f for f in src.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS]
    if not images:
        return []
    selected = random.sample(images, min(count, len(images)))
    filenames = []
    for img in selected:
        dest_name = f"styleref_{img.name}"
        dest = COMFYUI_INPUT_DIR / dest_name
        shutil.copy2(str(img), str(dest))
        filenames.append(dest_name)
    return filenames


async def upload_style_image_to_comfyui(filepath: Path) -> str:
    """Upload a single image to ComfyUI's input directory via API."""
    dest_name = f"styleref_{filepath.name}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        with open(filepath, "rb") as f:
            resp = await client.post(
                f"{COMFYUI_URL}/upload/image",
                files={"image": (dest_name, f, "image/png")},
                data={"overwrite": "true"},
            )
        if resp.status_code == 200:
            return resp.json().get("name", dest_name)
    return dest_name


async def prepare_style_images_via_api(source_path: str, count: int = 4) -> list[str]:
    """Select random images and upload to ComfyUI via HTTP API.

    This works regardless of shared filesystem between containers.
    """
    src = Path(source_path)
    if not src.is_dir():
        return []
    images = [f for f in src.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS]
    if not images:
        return []
    selected = random.sample(images, min(count, len(images)))
    filenames = []
    for img in selected:
        name = await upload_style_image_to_comfyui(img)
        filenames.append(name)
    return filenames


def inject_ipadapter_nodes(wf: dict, image_filenames: list[str],
                           weight: float = 0.7,
                           weight_type: str = "style transfer") -> dict:
    """Inject IP-Adapter nodes into an SDXL Eff. Loader workflow.

    Adds:
      900: LoadImage (reference image)
      901: IPAdapterUnifiedLoader (loads IP-Adapter model)
      902: IPAdapterAdvanced (applies style to model)

    Rewires: node 362 (Pack SDXL Tuple) base_model from 363→902.
    """
    if "362" not in wf or "363" not in wf:
        return wf
    if not image_filenames:
        return wf

    # Load up to 4 reference images and combine their embeddings
    # This produces a more stable style extraction than a single image
    for idx, fname in enumerate(image_filenames[:4]):
        wf[f"90{idx}"] = {
            "inputs": {"image": fname},
            "class_type": "LoadImage",
            "_meta": {"title": f"Style Reference {idx + 1}"},
        }

    # Node 910: IPAdapter Unified Loader — loads model + ipadapter
    wf["910"] = {
        "inputs": {
            "preset": "PLUS (high strength)",
            "model": ["363", 0],
        },
        "class_type": "IPAdapterUnifiedLoader",
        "_meta": {"title": "IPAdapter Loader"},
    }

    num_refs = min(len(image_filenames), 4)

    if num_refs == 1:
        # Single image: apply directly via IPAdapterAdvanced
        wf["940"] = {
            "inputs": {
                "weight": weight,
                "weight_type": weight_type,
                "combine_embeds": "concat",
                "start_at": 0.0,
                "end_at": 1.0,
                "embeds_scaling": "V only",
                "model": ["910", 0],
                "ipadapter": ["910", 1],
                "image": ["900", 0],
            },
            "class_type": "IPAdapterAdvanced",
            "_meta": {"title": "IPAdapter Style Transfer"},
        }
    else:
        # Multiple images: encode each, combine, apply via IPAdapterEmbeds
        embed_ids = []
        for idx in range(num_refs):
            eid = f"92{idx}"
            wf[eid] = {
                "inputs": {
                    "ipadapter": ["910", 1],
                    "image": [f"90{idx}", 0],
                    "weight": weight,
                },
                "class_type": "IPAdapterEncoder",
                "_meta": {"title": f"Encode Style {idx + 1}"},
            }
            embed_ids.append(eid)

        # Combine all embeddings (inputs are embed1..embed5, 1-indexed)
        combine_inputs = {"method": "average"}
        for idx, eid in enumerate(embed_ids):
            combine_inputs[f"embed{idx + 1}"] = [eid, 0]
        wf["930"] = {
            "inputs": combine_inputs,
            "class_type": "IPAdapterCombineEmbeds",
            "_meta": {"title": "Combine Style Embeds"},
        }

        # Apply combined embeddings
        wf["940"] = {
            "inputs": {
                "weight": weight,
                "weight_type": weight_type,
                "start_at": 0.0,
                "end_at": 1.0,
                "embeds_scaling": "V only",
                "model": ["910", 0],
                "ipadapter": ["910", 1],
                "pos_embed": ["930", 0],
            },
            "class_type": "IPAdapterEmbeds",
            "_meta": {"title": "IPAdapter Style Transfer"},
        }

    # Rewire: Pack SDXL Tuple gets model from IPAdapter output instead of raw model
    wf["362"]["inputs"]["base_model"] = ["940", 0]

    return wf


def build_workflow(prompt: str, flow: str = "photo", seed: int = None,
                   batch_size: int = None, format: str = None,
                   cfg: float = None, steps: int = None,
                   upscale: bool = False, facedetail: bool = False,
                   style_images: list[str] = None,
                   style_weight: float = 0.7,
                   style_type: str = "style transfer") -> dict:
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
    actual_seed = seed or random.randint(0, 2**32 - 1)
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

    # Format → Aspect Ratio (for API flows like Nano Banana)
    if "aspect_ratio" in node_map:
        format_map = flow_config.get("format_to_aspect", {})
        fmt_key = (format or "square").lower().strip()
        ar = format_map.get(fmt_key, "1:1")
        am = node_map["aspect_ratio"]
        if am["node"] in wf:
            wf[am["node"]]["inputs"][am["field"]] = ar
    else:
        # Format → Width/Height (for local SD/XL flows)
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

    # Dynamic filename prefix: img_YYMMDD-HHMM
    ts = datetime.now().strftime("%y%m%d-%H%M")
    for nid, node in wf.items():
        if node.get("class_type") == "SaveImage" and "filename_prefix" in node.get("inputs", {}):
            old = node["inputs"]["filename_prefix"]
            node["inputs"]["filename_prefix"] = f"{old}_{ts}"

    # IP-Adapter style injection
    if style_images and flow in IPADAPTER_FLOWS:
        wf = inject_ipadapter_nodes(wf, style_images, weight=style_weight, weight_type=style_type)

    return wf


async def queue_prompt(workflow: dict) -> str:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(f"{COMFYUI_URL}/prompt", json={"prompt": workflow})
        if resp.status_code == 200:
            data = resp.json()
            if "prompt_id" in data:
                return data["prompt_id"]
            raise Exception(f"ComfyUI error: {data.get('error', data)}")
        raise Exception(f"ComfyUI HTTP {resp.status_code}: {resp.text[:800]}")


async def poll_completion(prompt_id: str, timeout: int = 180, interval: float = 2.0) -> dict:
    elapsed = 0
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
    for node_id, node_output in outputs.items():
        images = node_output.get("images", [])
        for img in images:
            if img.get("type") == "output":
                filenames.append(img["filename"])
    return filenames


def extract_video_filenames(history: dict) -> list[str]:
    filenames = []
    outputs = history.get("outputs", {})
    for node_id, node_output in outputs.items():
        # ComfyUI returns video files under "images" key with animated=true
        if node_output.get("animated"):
            for item in node_output.get("images", []):
                if item.get("type") == "output":
                    subfolder = item.get("subfolder", "")
                    fname = item["filename"]
                    filenames.append(f"{subfolder}/{fname}" if subfolder else fname)
    return filenames


async def generate_images(prompt: str, flow: str = "photo", batch_size: int = None,
                          format: str = None, cfg: float = None, steps: int = None,
                          seed: int = None, upscale: bool = False,
                          facedetail: bool = False,
                          style_images: list[str] = None,
                          style_weight: float = 0.7,
                          style_type: str = "style transfer") -> dict:
    flow = resolve_flow(flow)
    flow_info = get_flow_info(flow)
    actual_seed = seed or random.randint(0, 2**32 - 1)
    workflow = build_workflow(prompt, flow=flow, seed=actual_seed,
                             batch_size=batch_size, format=format,
                             cfg=cfg, steps=steps, upscale=upscale,
                             facedetail=facedetail,
                             style_images=style_images,
                             style_weight=style_weight,
                             style_type=style_type)
    timeout = 120 if flow == "sd15" else 300
    prompt_id = await queue_prompt(workflow)
    history = await poll_completion(prompt_id, timeout=timeout)
    filenames = extract_filenames(history)

    images = []
    for i, fname in enumerate(filenames):
        images.append({
            "filename": fname,
            "url": f"/comfyui/wip/{fname}",
            "variant": i + 1,
        })

    return {
        "subtype": "image_variants",
        "prompt": prompt,
        "flow": flow,
        "flow_name": flow_info["name"],
        "seed": actual_seed,
        "prompt_id": prompt_id,
        "images": images,
        "count": len(images),
    }


def build_video_workflow(prompt: str, flow: str = "wan-t2v", seed: int = None,
                         format: str = None, steps: int = None,
                         length: int = None, fps: int = None,
                         start_image: str = None, end_image: str = None) -> dict:
    flow = resolve_flow(flow)
    registry = load_registry()
    flow_config = registry["flows"][flow]
    node_map = flow_config.get("node_map", {})
    wf = copy.deepcopy(load_workflow(flow))

    # Prompt
    if "prompt" in node_map:
        pm = node_map["prompt"]
        if pm["node"] in wf:
            wf[pm["node"]]["inputs"][pm["field"]] = prompt

    # Seed
    actual_seed = seed or random.randint(0, 2**32 - 1)
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

    # Length (frames)
    if length is not None and "length" in node_map:
        lm = node_map["length"]
        if lm["node"] in wf:
            wf[lm["node"]]["inputs"][lm["field"]] = int(length)

    # FPS
    if fps is not None and "fps" in node_map:
        fm = node_map["fps"]
        if fm["node"] in wf:
            wf[fm["node"]]["inputs"][fm["field"]] = int(fps)

    # Start image (i2v, i2i2v)
    if start_image and "start_image" in node_map:
        si = node_map["start_image"]
        if si["node"] in wf:
            wf[si["node"]]["inputs"][si["field"]] = start_image

    # End image (i2i2v)
    if end_image and "end_image" in node_map:
        ei = node_map["end_image"]
        if ei["node"] in wf:
            wf[ei["node"]]["inputs"][ei["field"]] = end_image

    # Dynamic filename prefix: vid_YYMMDD-HHMM
    ts = datetime.now().strftime("%y%m%d-%H%M")
    for nid, node in wf.items():
        if node.get("class_type") == "SaveVideo" and "filename_prefix" in node.get("inputs", {}):
            old = node["inputs"]["filename_prefix"]
            # Keep subfolder, replace prefix: "video/vid" → "video/vid_260427-1300"
            node["inputs"]["filename_prefix"] = f"{old}_{ts}"

    return wf


async def generate_video(prompt: str, flow: str = "wan-t2v", format: str = None,
                         steps: int = None, seed: int = None,
                         length: int = None, fps: int = None,
                         start_image: str = None, end_image: str = None) -> dict:
    flow = resolve_flow(flow)
    flow_info = get_flow_info(flow)
    actual_seed = seed or random.randint(0, 2**32 - 1)
    workflow = build_video_workflow(prompt, flow=flow, seed=actual_seed,
                                   format=format, steps=steps,
                                   length=length, fps=fps,
                                   start_image=start_image, end_image=end_image)
    prompt_id = await queue_prompt(workflow)
    history = await poll_completion(prompt_id, timeout=600)
    filenames = extract_video_filenames(history)

    if not filenames:
        return {"subtype": "video_result", "video_url": None, "error": "No video output found"}

    fname = filenames[0]
    return {
        "subtype": "video_result",
        "prompt": prompt,
        "flow": flow,
        "flow_name": flow_info["name"],
        "seed": actual_seed,
        "prompt_id": prompt_id,
        "video_url": f"/comfyui/wip/{fname}",
        "filename": fname.split("/")[-1],
    }


def parse_vid_command(raw: str) -> dict:
    parts = raw.strip()
    if parts.lower().startswith("/vid"):
        parts = parts[4:].strip()

    flow = None
    format = None
    steps = None
    seed = None
    length = None
    fps = None
    start_image = None
    end_image = None

    tokens = parts.split()
    prompt_tokens = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == "--flow" and i + 1 < len(tokens):
            flow = tokens[i + 1]; i += 2
        elif tok == "--format" and i + 1 < len(tokens):
            format = tokens[i + 1]; i += 2
        elif tok == "--steps" and i + 1 < len(tokens):
            try: steps = max(2, min(50, int(tokens[i + 1])))
            except ValueError: pass
            i += 2
        elif tok == "--seed" and i + 1 < len(tokens):
            try: seed = int(tokens[i + 1])
            except ValueError: pass
            i += 2
        elif tok == "--frames" and i + 1 < len(tokens):
            try: length = max(17, min(201, int(tokens[i + 1])))
            except ValueError: length = None
            i += 2
        elif tok == "--fps" and i + 1 < len(tokens):
            try: fps = max(8, min(60, int(tokens[i + 1])))
            except ValueError: fps = None
            i += 2
        elif tok == "--startframe" and i + 1 < len(tokens):
            start_image = tokens[i + 1]; i += 2
        elif tok == "--endframe" and i + 1 < len(tokens):
            end_image = tokens[i + 1]; i += 2
        elif tok.startswith("--"):
            i += 1
        else:
            prompt_tokens.append(tok); i += 1

    return {
        "prompt": " ".join(prompt_tokens),
        "flow": flow or "wan-t2v",
        "format": format,
        "steps": steps,
        "seed": seed,
        "length": length,
        "fps": fps,
        "start_image": start_image,
        "end_image": end_image,
    }


def parse_img_command(raw: str) -> dict:
    parts = raw.strip()
    if parts.lower().startswith("/img"):
        parts = parts[4:].strip()

    flow = None
    count = None
    format = None
    cfg = None
    steps = None
    seed = None
    upscale = False
    facedetail = False
    style = None
    style_weight = None
    style_type = None

    tokens = parts.split()
    prompt_tokens = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == "--flow" and i + 1 < len(tokens):
            flow = tokens[i + 1]; i += 2
        elif tok == "--format" and i + 1 < len(tokens):
            format = tokens[i + 1]; i += 2
        elif tok == "--count" and i + 1 < len(tokens):
            try: count = max(1, min(8, int(tokens[i + 1])))
            except ValueError: pass
            i += 2
        elif tok == "--steps" and i + 1 < len(tokens):
            try: steps = max(10, min(50, int(tokens[i + 1])))
            except ValueError: pass
            i += 2
        elif tok == "--cfg" and i + 1 < len(tokens):
            try: cfg = max(1.0, min(15.0, float(tokens[i + 1])))
            except ValueError: pass
            i += 2
        elif tok == "--seed" and i + 1 < len(tokens):
            try: seed = int(tokens[i + 1])
            except ValueError: pass
            i += 2
        elif tok == "--style" and i + 1 < len(tokens):
            style = tokens[i + 1]; i += 2
        elif tok == "--style-weight" and i + 1 < len(tokens):
            try: style_weight = max(0.0, min(1.0, float(tokens[i + 1])))
            except ValueError: pass
            i += 2
        elif tok == "--style-type" and i + 1 < len(tokens):
            style_type = tokens[i + 1].replace("_", " "); i += 2
        elif tok == "--upscale":
            upscale = True; i += 1
        elif tok == "--facedetail":
            facedetail = True; i += 1
        elif tok.startswith("--"):
            flow = tok[2:]; i += 1
        else:
            prompt_tokens.append(tok); i += 1

    return {
        "prompt": " ".join(prompt_tokens),
        "flow": flow or load_registry().get("default_flow", "photo"),
        "count": count,
        "format": format,
        "cfg": cfg,
        "steps": steps,
        "seed": seed,
        "upscale": upscale,
        "facedetail": facedetail,
        "style": style,
        "style_weight": style_weight,
        "style_type": style_type,
    }


# ============================================================
# EXPANDER — Outpaint / Image Expansion
# ============================================================

async def upload_image_url_to_comfyui(image_url: str) -> str:
    """Read image from local volume and upload to ComfyUI input directory."""
    # Map URL path to local filesystem path
    # /comfyui/wip/filename.png → /images/wip/filename.png (Pilot volume mount)
    filename = Path(image_url).name
    local_path = None

    if "/comfyui/wip/" in image_url:
        local_path = Path("/images/wip") / filename
    elif "/output/" in image_url:
        local_path = Path("/output/comfyui-wip") / filename

    dest_name = f"expand_{filename}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        if local_path and local_path.exists():
            # Read from local volume mount
            image_data = local_path.read_bytes()
        else:
            # Fallback: try HTTP download via nginx
            download_url = f"http://nginx-images:80{image_url}" if image_url.startswith("/") else image_url
            resp = await client.get(download_url)
            if resp.status_code != 200:
                raise Exception(f"Failed to download image: {resp.status_code} (tried {download_url})")
            image_data = resp.content

        # Upload to ComfyUI
        upload_resp = await client.post(
            f"{COMFYUI_URL}/upload/image",
            files={"image": (dest_name, image_data, "image/png")},
            data={"overwrite": "true"},
        )
        if upload_resp.status_code == 200:
            return upload_resp.json().get("name", dest_name)
    return dest_name


async def expand_image(image_url: str, prompt: str = "",
                       target_size: int = 1920,
                       seed: int = None,
                       steps: int = None,
                       feathering: int = None) -> dict:
    """Expand an image to target_size x target_size using outpainting.
    Calculates padding based on source image dimensions.
    Default: 1024→1920 = 448px each side.
    """
    actual_seed = seed or random.randint(0, 2**32 - 1)

    # Upload source image to ComfyUI
    comfyui_filename = await upload_image_url_to_comfyui(image_url)

    # Calculate padding (assume square source, default 1024→1920)
    source_size = 1024
    pad = max(0, (target_size - source_size) // 2)

    # Load and configure workflow
    flow = "expand"
    registry = load_registry()
    flow_config = registry["flows"][flow]
    node_map = flow_config.get("node_map", {})
    wf = copy.deepcopy(load_workflow(flow))

    # Inject parameters via node_map
    if "image" in node_map:
        nm = node_map["image"]
        wf[nm["node"]]["inputs"][nm["field"]] = comfyui_filename
    if "prompt" in node_map:
        nm = node_map["prompt"]
        default_prompt = "extend the background naturally, same style, same lighting, same scene, seamless continuation, high quality"
        wf[nm["node"]]["inputs"][nm["field"]] = prompt or default_prompt
    if "seed" in node_map:
        nm = node_map["seed"]
        wf[nm["node"]]["inputs"][nm["field"]] = actual_seed
    # Set padding on all four sides
    for pad_key in ["pad_left", "pad_top", "pad_right", "pad_bottom"]:
        if pad_key in node_map:
            nm = node_map[pad_key]
            wf[nm["node"]]["inputs"][nm["field"]] = pad
    # Steps override
    if steps and "steps" in node_map:
        nm = node_map["steps"]
        wf[nm["node"]]["inputs"][nm["field"]] = steps
    # Feathering override
    if feathering is not None and "feathering" in node_map:
        nm = node_map["feathering"]
        wf[nm["node"]]["inputs"][nm["field"]] = feathering

    # Execute
    prompt_id = await queue_prompt(wf)
    history = await poll_completion(prompt_id, timeout=300)
    filenames = extract_filenames(history)

    images = []
    for fname in filenames:
        images.append({
            "filename": fname,
            "url": f"/comfyui/wip/{fname}",
        })

    return {
        "subtype": "expand_result",
        "source_image": image_url,
        "prompt": prompt,
        "seed": actual_seed,
        "target": f"{target_size}x{target_size}",
        "prompt_id": prompt_id,
        "images": images,
        "count": len(images),
    }
