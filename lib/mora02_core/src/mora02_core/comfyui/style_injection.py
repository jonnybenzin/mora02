"""IP-Adapter style reference injection for SDXL Eff. Loader workflows.

Adds nodes 90x (LoadImage refs), 910 (IPAdapterUnifiedLoader), 92x (encoders
when multi-ref), 930 (CombineEmbeds), 940 (IPAdapterAdvanced/Embeds).
Rewires the Pack SDXL Tuple (node 362) to read its base_model from 940
instead of the raw model node 363.
"""

import random
import shutil
from pathlib import Path

import httpx

from mora02_core._common import get_logger
from mora02_core.comfyui._config import COMFYUI_INPUT_DIR, COMFYUI_URL

_log = get_logger("mora02_core.comfyui.style_injection")

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"}

# Flows that support IP-Adapter injection (SDXL with Eff. Loader pattern)
IPADAPTER_FLOWS = {"photo", "concept", "epic"}


def prepare_style_images(source_path: str, count: int = 4) -> list[str]:
    """Copy N random style images from a folder into ComfyUI's input dir.

    Returns the filenames (relative to COMFYUI_INPUT_DIR). Used when the
    pilot container and ComfyUI share a bind mount; falls back to the
    via_api variant otherwise.
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
    """Upload a single image to ComfyUI's input dir via HTTP /upload/image."""
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
    """HTTP-based variant — works without shared filesystem between containers."""
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


def inject_ipadapter_nodes(
    wf: dict,
    image_filenames: list[str],
    weight: float = 0.7,
    weight_type: str = "style transfer",
) -> dict:
    """Inject IP-Adapter nodes into an SDXL Eff. Loader workflow.

    Single-image path uses IPAdapterAdvanced; multi-image path encodes each
    reference separately and combines the embeddings before applying.
    No-op if the workflow doesn't have the expected nodes 362/363, or if
    image_filenames is empty.
    """
    if "362" not in wf or "363" not in wf:
        return wf
    if not image_filenames:
        return wf

    # Load up to 4 reference images
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
        # Encode each reference separately, combine, then apply via Embeds
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

        # IPAdapterCombineEmbeds expects embed1..embed5 (1-indexed)
        combine_inputs = {"method": "average"}
        for idx, eid in enumerate(embed_ids):
            combine_inputs[f"embed{idx + 1}"] = [eid, 0]
        wf["930"] = {
            "inputs": combine_inputs,
            "class_type": "IPAdapterCombineEmbeds",
            "_meta": {"title": "Combine Style Embeds"},
        }

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

    # Pack SDXL Tuple gets model from IPAdapter output instead of raw model
    wf["362"]["inputs"]["base_model"] = ["940", 0]

    return wf
