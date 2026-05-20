"""mora02_core.comfyui — ComfyUI integration.

Phase 1.4: extracted from apps/pilot/comfyui_client.py.

Layout:
    _config.py        — env-overridable URL + paths
    client.py         — queue_prompt, poll_completion, extract_*
    registry.py       — load_registry, load_workflow, resolve_flow, list_flows
    builders.py       — build_workflow, build_video_workflow, parse_format
    style_injection.py — IP-Adapter node injection
    transforms.py     — expand_image, upscale_image
    api.py            — generate_images, generate_video (return assets: list[Asset])

Pilot's slash-command parsers (parse_img_command, parse_vid_command) stay
in apps/pilot/comfyui_client.py — that's pilot-UX, not library knowledge.
"""

from mora02_core.comfyui._config import (
    COMFYUI_INPUT_DIR,
    COMFYUI_STYLES_DIR,
    COMFYUI_URL,
    COMFYUI_WORKFLOWS_DIR,
)
from mora02_core.comfyui.api import generate_images, generate_video
from mora02_core.comfyui.builders import (
    FORMATS,
    FORMATS_TEST,
    build_video_workflow,
    build_workflow,
    parse_format,
)
from mora02_core.comfyui.client import (
    extract_error,
    extract_filenames,
    extract_video_filenames,
    poll_completion,
    queue_prompt,
)
from mora02_core.comfyui.registry import (
    get_flow_info,
    list_flows,
    load_registry,
    load_workflow,
    reload_flows,
    resolve_flow,
)
from mora02_core.comfyui.style_injection import (
    IMAGE_EXTENSIONS,
    IPADAPTER_FLOWS,
    inject_ipadapter_nodes,
    prepare_style_images,
    prepare_style_images_via_api,
    upload_style_image_to_comfyui,
)
from mora02_core.comfyui.transforms import (
    expand_image,
    upload_image_url_to_comfyui,
    upscale_image,
)

__all__ = [
    # config
    "COMFYUI_URL",
    "COMFYUI_INPUT_DIR",
    "COMFYUI_WORKFLOWS_DIR",
    "COMFYUI_STYLES_DIR",
    # high-level api
    "generate_images",
    "generate_video",
    # transforms
    "expand_image",
    "upscale_image",
    "upload_image_url_to_comfyui",
    # registry
    "load_registry",
    "load_workflow",
    "resolve_flow",
    "get_flow_info",
    "list_flows",
    "reload_flows",
    # builders
    "build_workflow",
    "build_video_workflow",
    "parse_format",
    "FORMATS",
    "FORMATS_TEST",
    # client
    "queue_prompt",
    "poll_completion",
    "extract_filenames",
    "extract_video_filenames",
    "extract_error",
    # style injection
    "prepare_style_images",
    "prepare_style_images_via_api",
    "upload_style_image_to_comfyui",
    "inject_ipadapter_nodes",
    "IPADAPTER_FLOWS",
    "IMAGE_EXTENSIONS",
]
