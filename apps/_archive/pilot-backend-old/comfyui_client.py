import httpx
import json
import asyncio
import random
import os
from config import settings


COMFYUI_URL = "http://comfyui:8188"
IMAGES_WIP_DIR = "/images/wip"  # mounted in pilot container
IMAGES_WIP_HOST = "/opt/mora02/output/_default/comfyui/wip"

# Base workflow for SD1.5 txt2img with batch_size 4
SD15_WORKFLOW = {
    "1": {
        "class_type": "CheckpointLoaderSimple",
        "inputs": {"ckpt_name": "sd_v1-5.safetensors"}
    },
    "2": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "", "clip": ["1", 1]}
    },
    "3": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "ugly, blurry, low quality, deformed, disfigured", "clip": ["1", 1]}
    },
    "4": {
        "class_type": "EmptyLatentImage",
        "inputs": {"width": 512, "height": 512, "batch_size": 4}
    },
    "5": {
        "class_type": "KSampler",
        "inputs": {
            "model": ["1", 0],
            "positive": ["2", 0],
            "negative": ["3", 0],
            "latent_image": ["4", 0],
            "seed": 0,
            "steps": 20,
            "cfg": 7.0,
            "sampler_name": "euler_ancestral",
            "scheduler": "normal",
            "denoise": 1.0
        }
    },
    "6": {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["5", 0], "vae": ["1", 2]}
    },
    "7": {
        "class_type": "SaveImage",
        "inputs": {"images": ["6", 0], "filename_prefix": "pilot"}
    }
}


def build_workflow(prompt: str, seed: int = None, batch_size: int = 4) -> dict:
    """Build a workflow dict with prompt and seed injected."""
    import copy
    wf = copy.deepcopy(SD15_WORKFLOW)
    wf["2"]["inputs"]["text"] = prompt
    wf["5"]["inputs"]["seed"] = seed or random.randint(0, 2**32 - 1)
    wf["4"]["inputs"]["batch_size"] = batch_size
    return wf


async def queue_prompt(workflow: dict) -> str:
    """Submit workflow to ComfyUI, return prompt_id."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{COMFYUI_URL}/prompt",
            json={"prompt": workflow})
        if resp.status_code == 200:
            data = resp.json()
            if "prompt_id" in data:
                return data["prompt_id"]
            raise Exception(f"ComfyUI error: {data.get('error', data)}")
        raise Exception(f"ComfyUI HTTP {resp.status_code}: {resp.text[:200]}")


async def poll_completion(prompt_id: str, timeout: int = 120, interval: float = 2.0) -> dict:
    """Poll ComfyUI history until generation is complete."""
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
    raise TimeoutError(f"ComfyUI generation timed out after {timeout}s")


def extract_filenames(history: dict) -> list[str]:
    """Extract output filenames from ComfyUI history response."""
    filenames = []
    outputs = history.get("outputs", {})
    for node_id, node_output in outputs.items():
        images = node_output.get("images", [])
        for img in images:
            filenames.append(img["filename"])
    return filenames


async def generate_images(prompt: str, batch_size: int = 4) -> dict:
    """Full flow: queue → poll → return filenames and URLs."""
    seed = random.randint(0, 2**32 - 1)
    workflow = build_workflow(prompt, seed=seed, batch_size=batch_size)

    prompt_id = await queue_prompt(workflow)

    history = await poll_completion(prompt_id, timeout=120)

    filenames = extract_filenames(history)

    # Build URLs via nginx-images
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
        "seed": seed,
        "prompt_id": prompt_id,
        "images": images,
        "count": len(images),
    }


def parse_img_command(raw: str) -> dict:
    """Parse /img command: /img prompt text --flow photo --count 4"""
    parts = raw.strip()
    if parts.lower().startswith("/img"):
        parts = parts[4:].strip()

    # Extract --flags
    flow = "sd15"
    count = 4
    tokens = parts.split()
    prompt_tokens = []
    i = 0
    while i < len(tokens):
        if tokens[i] == "--flow" and i + 1 < len(tokens):
            flow = tokens[i + 1]
            i += 2
        elif tokens[i] == "--count" and i + 1 < len(tokens):
            try:
                count = int(tokens[i + 1])
                count = max(1, min(8, count))
            except ValueError:
                pass
            i += 2
        elif tokens[i].startswith("--"):
            # shorthand: --photo, --illustration etc
            flow = tokens[i][2:]
            i += 1
        else:
            prompt_tokens.append(tokens[i])
            i += 1

    return {
        "prompt": " ".join(prompt_tokens),
        "flow": flow,
        "count": count,
    }
