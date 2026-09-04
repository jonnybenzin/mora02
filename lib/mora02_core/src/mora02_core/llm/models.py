"""MODELS registry — Anthropic + local Qwen via llama.cpp.

Single source of truth for model IDs and capabilities. The PRICES are NOT
here: they live in mora02_core.pricing, keyed by the API model name, and the
entries below take their cost fields from it. Two tables existed before and
disagreed by a factor of three on the same model (review 2, section E).
Update a price there, and every reader of this registry sees it.
"""

from mora02_core import auth, pricing

# The llama.cpp container is named llama-server for every profile, so this
# address is stable inside mora02-net and survives a profile switch. It is also
# the portable default: a host name like mora02.local only resolves on this one
# machine, and its port is bound to localhost, so a container reaching for it
# fails with a bare ConnectError. Override with QWEN_URL when calling from
# outside the compose network.
_QWEN_URL = auth.get("QWEN_URL", "http://llama-server:8080")

# Human labels for local llama.cpp profiles.
# Derived from mora02_core.llm.profiles.PROFILES (single source of truth).
# This constant is kept for backward compatibility with callers that imported
# it directly; new code should prefer profile_label() or PROFILES directly.
from mora02_core.llm.profiles import PROFILES as _PROFILES

LOCAL_PROFILE_LABELS = {name: meta["label"] for name, meta in _PROFILES.items()}

# `label`, `color`, `tier` drive UI rendering. `color` is the CSS-var key
# (defined in apps/pilot/ui/css/design-tokens.css as `--<color>`).
# `tier` is a free-form price marker shown right-aligned in the dropdown.
# Dict iteration order = UI dropdown order.
MODELS = {
    "qwen": {
        "name": "Qwen3-14B",
        "endpoint": f"{_QWEN_URL}/v1/chat/completions",
        "type": "openai_compatible",
        "supports_vision": False,
        "icon": "\U0001f3e0",
        "label": "QWEN",
        "color": "m-qwen",
        "tier": "",
    },
    "haiku": {
        "name": "claude-haiku-4-5-20251001",
        "type": "anthropic",
        "supports_vision": True,
        "icon": "⚡",
        "label": "HAIKU",
        "color": "m-haiku",
        "tier": "€",
    },
    "sonnet": {
        "name": "claude-sonnet-4-5-20250929",
        "type": "anthropic",
        "supports_vision": True,
        "icon": "\U0001f3af",
        "label": "SONNET",
        "color": "m-sonnet",
        "tier": "€€",
    },
    "opus": {
        "name": "claude-opus-4-6",
        "type": "anthropic",
        "supports_vision": True,
        "icon": "\U0001f9e0",
        "label": "OPUS",
        "color": "m-opus",
        "tier": "€€€",
    },
}


# Filled from the one price table rather than written down twice. A model with
# no price -- a local one, or one nobody has priced -- carries 0.0 and reports
# as costing nothing, which for the local ones is true.
for _entry in MODELS.values():
    _entry["cost_input_per_1m"], _entry["cost_output_per_1m"] = (
        pricing.rate_for(_entry.get("name")) or (0.0, 0.0)
    )
