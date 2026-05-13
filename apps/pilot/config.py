import json
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings

# ----------------------------------------------------------------------------
# LLM profile state — single source of truth is /llm-switch/current.json,
# written by /opt/mora02/scripts/llm-switch.sh on every successful switch.
# This file is mounted read-only into the pilot container.
# ----------------------------------------------------------------------------

_LLM_CURRENT_STATE_FILE = Path("/llm-switch/current.json")

# Human-readable labels, must stay in sync with
# apps/script-runner/app/scripts/llm_switcher.py PROFILES.
_LOCAL_PROFILE_LABELS = {
    "qwen3-14b": "Qwen3 14B",
    "qwen3-8b": "Qwen3 8B",
    "qwen25-7b": "Qwen2.5 7B",
    "qwen25-coder": "Qwen2.5 Coder",
    "nous-hermes": "Nous-Hermes",
    "magistral": "Magistral",
}


def get_local_profile_name() -> Optional[str]:
    """Return the currently active local-LLM profile key, or None if unknown."""
    try:
        data = json.loads(_LLM_CURRENT_STATE_FILE.read_text())
        name = data.get("profile")
        return name if isinstance(name, str) and name else None
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def get_local_profile_label() -> str:
    """Return a human label for the current local profile, or 'Local LLM'."""
    name = get_local_profile_name()
    if not name:
        return "Local LLM"
    return _LOCAL_PROFILE_LABELS.get(name, name)


class Settings(BaseSettings):
    qwen_url: str = "http://mora02.local:8080"
    anthropic_api_key: str = ""
    dify_api_url: str = "http://dify-new-api:5001"
    dify_api_key: str = ""
    script_runner_url: str = "http://script-runner:8096"
    blender_worker_url: str = "http://blender-worker:8097"
    pixeltext_assets_url: str = "http://mora02.local:8092/pixeltext"
    comfyui_url: str = "http://mora02.local:8188"
    searxng_url: str = "http://searxng:8080"
    baserow_url: str = "http://baserow:80"
    baserow_token: str = ""
    baserow_table_sessions: int = 571
    baserow_table_context: int = 572
    baserow_table_personas: int = 575
    baserow_table_known_issues: int = 573
    baserow_table_feedback: int = 576
    baserow_table_buckets: int = 577
    baserow_table_style_packs: int = 578
    baserow_table_posts: int = 557
    styles_base_path: str = "/data/styles"
    host: str = "0.0.0.0"
    port: int = 8098
    max_history: int = 100

    class Config:
        env_prefix = "PILOT_"


settings = Settings()

MODELS = {
    "qwen": {
        "name": "Qwen3-14B",
        "endpoint": f"{settings.qwen_url}/v1/chat/completions",
        "type": "openai_compatible",
        "cost_input_per_1m": 0.0,
        "cost_output_per_1m": 0.0,
        "supports_vision": False,
        "icon": "\U0001f3e0",
    },
    "haiku": {
        "name": "claude-haiku-4-5-20251001",
        "type": "anthropic",
        "cost_input_per_1m": 0.80,
        "cost_output_per_1m": 4.00,
        "supports_vision": True,
        "icon": "\u26a1",
    },
    "sonnet": {
        "name": "claude-sonnet-4-5-20250929",
        "type": "anthropic",
        "cost_input_per_1m": 3.00,
        "cost_output_per_1m": 15.00,
        "supports_vision": True,
        "icon": "\U0001f3af",
    },
    "opus": {
        "name": "claude-opus-4-6",
        "type": "anthropic",
        "cost_input_per_1m": 15.00,
        "cost_output_per_1m": 75.00,
        "supports_vision": True,
        "icon": "\U0001f9e0",
    },
}

DEFAULT_SYSTEM_PROMPT = """You are the Pilot Bot of the Mora02 Creative Factory.

## Your Role
- Advisor for architecture, strategy, debugging, documentation
- Orchestrator: you can delegate to local services via slash commands
- Respond concisely, factually, directly
- Respond in German unless the user writes in English
- Do NOT suggest next steps unless explicitly asked

## System
- Hardware: RTX 5090 (32GB VRAM), Ryzen 9 7950X, 64GB RAM
- OS: Ubuntu 24.04
- Local LLM: llama.cpp @ Port 8080 (profile-switchable from the dashboard)
- Free VRAM: ~17 GB for ComfyUI
- Stack: Docker Compose, ~26 containers

## Directives
1. Local first — no cloud dependencies
2. Open Source — no proprietary tools
3. Portable — must be reproducible on another system

## Available Slash Commands
When a natural language request maps to an action, suggest the matching command.

### Social Media
/post - Open Post Editor

### Roadmap
/rd - Active items
/rd [id] - Item details
/rd new "Title" - New item
/rd edit [id] key:"val" - Edit item
/rd done [id] - Complete item

### Creative
/gif - Create GIF
/typ - Text frames
/clip - Video clip
/stock [query] - Stock photo search
/pix TEXT - Render 3D pixel-cube typography in Blender (single word, MP4). For multi-word/styling use the PIXELTEXT tool page.

### Search & AI
/search [query] - Web search (SearXNG, local)
/img "prompt" - Generate image (ComfyUI)

## Communication
- Concise, max 5 points per answer
- Default language: German (unless user writes English)
- Answer the question, nothing more

## Baserow API Reference

Base URL: http://mora02.local:8085/api/database/rows/table/{TABLE_ID}/
Auth: Authorization: Token <BASEROW_TOKEN>  # injected from env at runtime
Always append: ?user_field_names=true

Tables:
- 557: sm_content (Social Media Posts)
- 569: roadmap
- 571: bot_sessions
- 572: bot_context
- 573: bot_known_issues
- 575: bot_personas

CRUD Operations:
- List:   GET    .../table/{ID}/?user_field_names=true
- Get:    GET    .../table/{ID}/{ROW}/?user_field_names=true
- Create: POST   .../table/{ID}/?user_field_names=true  (JSON body)
- Update: PATCH  .../table/{ID}/{ROW}/?user_field_names=true  (JSON body)
- Delete: DELETE .../table/{ID}/{ROW}/

When suggesting Baserow operations to the user, always provide the full curl command, ready to copy-paste.

## File Delivery Rules

When creating or modifying files:
- ALWAYS use cat > /absolute/path/file.ext << 'EOF' blocks
- NEVER just show code and say save this as...
- Write COMPLETE file content, not diffs
- After each file: include test command or checkpoint
- For downloadable files: use Script-Runner /save-file endpoint + provide mv/cp command

Target paths by file type:
- .md docs → /opt/mora02/docs/system/
- .py scripts → /opt/mora02/scripts/
- .yml/.yaml config → /opt/mora02/docker/
- .sh shell → /opt/mora02/scripts/
- Hugo files → ~/Schreibtisch/Mora02/apps/jonnybenzin_portfolio/hugo-site/
"""
