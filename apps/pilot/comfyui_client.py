"""
Mora02 ComfyUI Client — File-based workflow system with node_map.
Supports: flow, format, cfg, steps, seed, batch, upscale, facedetail.
"""

import httpx
import json
import asyncio
import random
import copy
from pathlib import Path

COMFYUI_URL = "http://comfyui:8188"
WORKFLOWS_DIR = Path("/workflows")
_registry_cache = None
_workflow_cache = {}

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


def build_workflow(prompt: str, flow: str = "photo", seed: int = None,
                   batch_size: int = None, format: str = None,
                   cfg: float = None, steps: int = None,
                   upscale: bool = False, facedetail: bool = False) -> dict:
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

    # CFG
    if cfg is not None and "cfg" in node_map:
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

    return wf


async def queue_prompt(workflow: dict) -> str:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(f"{COMFYUI_URL}/prompt", json={"prompt": workflow})
        if resp.status_code == 200:
            data = resp.json()
            if "prompt_id" in data:
                return data["prompt_id"]
            raise Exception(f"ComfyUI error: {data.get('error', data)}")
        raise Exception(f"ComfyUI HTTP {resp.status_code}: {resp.text[:200]}")


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


async def generate_images(prompt: str, flow: str = "photo", batch_size: int = None,
                          format: str = None, cfg: float = None, steps: int = None,
                          seed: int = None, upscale: bool = False,
                          facedetail: bool = False) -> dict:
    flow = resolve_flow(flow)
    flow_info = get_flow_info(flow)
    actual_seed = seed or random.randint(0, 2**32 - 1)
    workflow = build_workflow(prompt, flow=flow, seed=actual_seed,
                             batch_size=batch_size, format=format,
                             cfg=cfg, steps=steps, upscale=upscale,
                             facedetail=facedetail)
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
    }
