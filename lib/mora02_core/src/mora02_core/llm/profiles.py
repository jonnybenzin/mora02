"""Local-LLM profile metadata — single source of truth.

This module is the canonical place for the local-LLM profile catalog.
Other modules in mora02_core derive from it:
    - ``llm.models.LOCAL_PROFILE_LABELS`` (backward-compat shim)
    - ``llm.switcher`` (validates profile names against this dict)

The host-side switcher script (``scripts/llm-switch.sh``) carries its own
whitelist for security reasons; keep it in sync when adding profiles here.
"""

from typing import TypedDict


class ProfileMeta(TypedDict):
    label: str
    category: str
    model: str
    vram: str
    description: str


PROFILES: dict[str, ProfileMeta] = {
    "qwen3-14b": {
        "label": "Qwen3 14B",
        "category": "Balanced",
        "model": "Qwen3-14B-Q4_K_M.gguf",
        "vram": "~15.5 GB",
        "description": "Default general-purpose",
    },
    "qwen3-8b": {
        "label": "Qwen3 8B",
        "category": "Fast",
        "model": "Qwen3-8B-Q4_K_M.gguf",
        "vram": "~9 GB",
        "description": "Faster, lower VRAM",
    },

    "qwen36-27b": {
        "label": "Qwen3.6 27B",
        "category": "Agentic",
        "model": "Qwen3.6-27B-UD-IQ3_XXS.gguf",
        "vram": "~16 GB",
        "description": "Agentic-trained 27B, 3-bit (candidate)",
    },
    "glimmer-30b": {
        "label": "Muse Glimmer 30B",
        "category": "Agentic",
        "model": "Muse-Glimmer-30B-UD-Q3_K_XL.gguf",
        "vram": "~16 GB",
        "description": "Meta agent-loop model, 3-bit (candidate)",
    },

}


def profile_names() -> set[str]:
    """Return the set of valid profile names — for input validation."""
    return set(PROFILES.keys())


def profile_label(name: str) -> str:
    """Return the human label for a profile name, or the name itself as fallback."""
    return PROFILES.get(name, {}).get("label", name)


def profiles_as_list() -> list[dict]:
    """Return the profiles as a list with 'name' added — for HTTP API responses."""
    return [{"name": name, **meta} for name, meta in PROFILES.items()]
