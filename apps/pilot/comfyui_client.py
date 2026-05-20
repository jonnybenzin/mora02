"""Pilot's pilot-specific ComfyUI surface.

Phase 1.4: all heavy lifting moved to mora02_core.comfyui. This file keeps
only the slash-command parsers (`parse_img_command`, `parse_vid_command`)
because they encode pilot-UX, not library knowledge — and re-exports the
library names so legacy `from comfyui_client import X` keeps working
without touching bot_bridge.py.
"""

# Re-exports — legacy callers in bot_bridge.py use `from comfyui_client import ...`.
from mora02_core.comfyui import (  # noqa: F401
    IPADAPTER_FLOWS,
    IMAGE_EXTENSIONS,
    expand_image,
    generate_images,
    generate_video,
    get_flow_info,
    list_flows,
    load_registry,
    prepare_style_images_via_api,
    reload_flows,
    resolve_flow,
    upscale_image,
)


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
    testrun = False
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
        elif tok == "--testrun":
            testrun = True; i += 1
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
        "testrun": testrun,
        "style": style,
        "style_weight": style_weight,
        "style_type": style_type,
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
