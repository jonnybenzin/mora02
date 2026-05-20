"""Config constants for ComfyUI integration.

All paths / URLs are env-overridable. Defaults match the in-container layout
that the pilot Dockerfile mounts (see docker/docker-compose.yml pilot block).
"""

from pathlib import Path

from mora02_core import auth

COMFYUI_URL = auth.get("COMFYUI_URL", "http://comfyui:8188")
COMFYUI_INPUT_DIR = Path(auth.get("COMFYUI_INPUT_DIR", "/comfyui-input"))
COMFYUI_WORKFLOWS_DIR = Path(auth.get("COMFYUI_WORKFLOWS_DIR", "/workflows"))
COMFYUI_STYLES_DIR = Path(auth.get("COMFYUI_STYLES_DIR", "/data/styles"))
