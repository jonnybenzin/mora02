"""Workflow registry: maps logical flow names → JSON workflow files.

Source-of-truth is the JSON registry at COMFYUI_WORKFLOWS_DIR/_registry.json.
Individual workflow files (concept.json, flux.json, etc.) live alongside it.
Pilot owns these files today (apps/pilot/workflows/); a second consumer could
point COMFYUI_WORKFLOWS_DIR elsewhere.
"""

import json

from mora02_core._common import get_logger
from mora02_core.comfyui._config import COMFYUI_WORKFLOWS_DIR

_log = get_logger("mora02_core.comfyui.registry")

_registry_cache: dict | None = None
_workflow_cache: dict[str, dict] = {}


def load_registry(force: bool = False) -> dict:
    global _registry_cache
    if _registry_cache is not None and not force:
        return _registry_cache
    reg_path = COMFYUI_WORKFLOWS_DIR / "_registry.json"
    if not reg_path.exists():
        raise FileNotFoundError(f"Registry not found: {reg_path}")
    with open(reg_path) as f:
        _registry_cache = json.load(f)
    _log.info("loaded registry from %s (%d flows)", reg_path, len(_registry_cache.get("flows", {})))
    return _registry_cache


def load_workflow(flow_key: str) -> dict:
    if flow_key in _workflow_cache:
        return _workflow_cache[flow_key]
    registry = load_registry()
    flow_config = registry["flows"].get(flow_key)
    if not flow_config:
        raise ValueError(f"Unknown flow: {flow_key}")
    wf_path = COMFYUI_WORKFLOWS_DIR / flow_config["file"]
    if not wf_path.exists():
        raise FileNotFoundError(f"Workflow not found: {wf_path}")
    with open(wf_path) as f:
        wf = json.load(f)
    _workflow_cache[flow_key] = wf
    return wf


def resolve_flow(name: str) -> str:
    """Map a user-facing flow name or alias to the canonical registry key."""
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
    return [
        {
            "flow": k,
            "name": v["name"],
            "max_batch": v.get("max_batch", 4),
            "needs_vram": v.get("needs_vram", False),
            "aliases": v.get("aliases", []),
        }
        for k, v in registry["flows"].items()
    ]


def reload_flows() -> None:
    global _registry_cache, _workflow_cache
    _registry_cache = None
    _workflow_cache = {}
    load_registry(force=True)
