"""Config constants for ComfyUI integration.

All paths / URLs are env-overridable. Defaults match the in-container layout
that the pilot Dockerfile mounts (see docker/docker-compose.yml pilot block).
"""

from pathlib import Path

from mora02_core import auth

COMFYUI_URL = auth.get("COMFYUI_URL", "http://comfyui:8188")
COMFYUI_INPUT_DIR = Path(auth.get("COMFYUI_INPUT_DIR", "/comfyui-input"))

# Workflow JSON templates ship with the library itself (package-data in
# pyproject.toml). Path(__file__).parent resolves to .../mora02_core/comfyui/
# both in src-layout dev installs and in pip-installed site-packages.
_DEFAULT_WORKFLOWS_DIR = Path(__file__).parent / "workflows"
COMFYUI_WORKFLOWS_DIR = Path(auth.get("COMFYUI_WORKFLOWS_DIR", str(_DEFAULT_WORKFLOWS_DIR)))

COMFYUI_STYLES_DIR = Path(auth.get("COMFYUI_STYLES_DIR", "/data/styles"))
