"""MODELS registry — Anthropic + local Qwen via llama.cpp.

Single source of truth for model IDs, pricing, and capabilities.
Pricing is per 1M tokens, USD. Update when Anthropic publishes new rates.
"""

from mora02_core import auth

_QWEN_URL = auth.get("QWEN_URL", "http://mora02.local:8080")

# Human labels for local llama.cpp profiles. Must stay in sync with
# apps/script-runner/app/scripts/llm_switcher.py PROFILES.
LOCAL_PROFILE_LABELS = {
    "qwen3-14b": "Qwen3 14B",
    "qwen3-8b": "Qwen3 8B",
    "qwen25-7b": "Qwen2.5 7B",
    "qwen25-coder": "Qwen2.5 Coder",
    "nous-hermes": "Nous-Hermes",
    "magistral": "Magistral",
}

# `label`, `color`, `tier` drive UI rendering. `color` is the CSS-var key
# (defined in apps/pilot/ui/css/design-tokens.css as `--<color>`).
# `tier` is a free-form price marker shown right-aligned in the dropdown.
# Dict iteration order = UI dropdown order.
MODELS = {
    "qwen": {
        "name": "Qwen3-14B",
        "endpoint": f"{_QWEN_URL}/v1/chat/completions",
        "type": "openai_compatible",
        "cost_input_per_1m": 0.0,
        "cost_output_per_1m": 0.0,
        "supports_vision": False,
        "icon": "\U0001f3e0",
        "label": "QWEN",
        "color": "m-qwen",
        "tier": "",
    },
    "haiku": {
        "name": "claude-haiku-4-5-20251001",
        "type": "anthropic",
        "cost_input_per_1m": 0.80,
        "cost_output_per_1m": 4.00,
        "supports_vision": True,
        "icon": "⚡",
        "label": "HAIKU",
        "color": "m-haiku",
        "tier": "€",
    },
    "sonnet": {
        "name": "claude-sonnet-4-5-20250929",
        "type": "anthropic",
        "cost_input_per_1m": 3.00,
        "cost_output_per_1m": 15.00,
        "supports_vision": True,
        "icon": "\U0001f3af",
        "label": "SONNET",
        "color": "m-sonnet",
        "tier": "€€",
    },
    "opus": {
        "name": "claude-opus-4-6",
        "type": "anthropic",
        "cost_input_per_1m": 15.00,
        "cost_output_per_1m": 75.00,
        "supports_vision": True,
        "icon": "\U0001f9e0",
        "label": "OPUS",
        "color": "m-opus",
        "tier": "€€€",
    },
}
