#!/usr/bin/env python3
"""
Mora02 Script Runner API

The FastAPI app and the routes that belong to the service as a whole: health,
the API index, the Pilot's file downloads, the LLM profile switch and the GPU
memory release. Everything else is a router this module includes:

    media.py      sessions, gifer / clipper / typer, stock photos, finalize
    steps.py      the pipeline step verbs (/pipeline/step/{op})
    pipelines.py  run / re-run / resume a flow, the flow library, the runs view
    agents.py     the agent layer
    mcp_tools.py  the MCP surface (a protocol, not an endpoint)
    speech.py     TTS and the Chatterbox container
    runtime.py    constants and the path rules every router shares
"""

import re
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from agents import router as agents_router
from mcp_tools import router as mcp_router
from media import router as media_router
from pipelines import router as pipelines_router
from speech import router as speech_router
from steps import router as steps_router
from runtime import DATA_DIR, SERVICE_VERSION, WIP_DIR, create_timestamp

# ============================================================================
# APP SETUP
# ============================================================================

app = FastAPI(
    title="Mora02 Script Runner",
    description="API for gifer, clipper, typer scripts",
    version=SERVICE_VERSION,
)

app.include_router(media_router)
app.include_router(steps_router)
app.include_router(pipelines_router)
app.include_router(agents_router)
app.include_router(mcp_router)
app.include_router(speech_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# HEALTH CHECK
# ============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "scripts": ["gifer", "clipper", "typer", "pexels", "pixabay"],
        "wip_sessions": len(list(WIP_DIR.glob("*"))),
        "version": SERVICE_VERSION
    }

@app.get("/")
async def root():
    """API info"""
    return {
        "service": "Mora02 Script Runner",
        "version": SERVICE_VERSION,
        "endpoints": {
            "session": "/session/create",
            "upload": "/upload/{session_id}",
            "gifer": "/run/gifer",
            "typer": "/run/typer", 
            "clipper": "/run/clipper",
            "preview": "/preview/{session_id}/{filename}",
            "finalize": "/finalize (legacy)",
            "finalize-session": "/finalize-session (with Baserow)",
            "publish-asset": "/publish-asset (copy to channel)",
            "search-pexels": "/search/pexels",
            "search-pixabay": "/search/pixabay",
            "download-stock": "/download/stock"
        }
    }

# ============================================================================
# ENDPOINTS - FILE SAVE (Download-Buttons für Pilot)
# ============================================================================


DOWNLOADS_DIR = DATA_DIR / "downloads"
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
NGINX_DOWNLOADS_URL = "http://mora02.local:8092/script-bot-downloads"

class SaveFileRequest(BaseModel):
    filename: str
    content: str
    add_timestamp: bool = True

@app.post("/save-file")
async def save_file(request: SaveFileRequest):
    filename = re.sub(r'[^\w\-_.]', '_', request.filename)
    if request.add_timestamp and not re.match(r'^\d{6}-\d{4}_', filename):
        timestamp = create_timestamp()
        filename = f"{timestamp}_{filename}"
    filepath = DOWNLOADS_DIR / filename
    filepath.write_text(request.content, encoding='utf-8')
    ext = filepath.suffix.lower()
    targets = {
        '.py': '/opt/mora02/scripts/',
        '.sh': '/opt/mora02/scripts/',
        '.md': '/opt/mora02/docs/system/',
        '.yml': '/opt/mora02/docker/',
        '.yaml': '/opt/mora02/docker/',
        '.json': '/opt/mora02/config/',
        '.html': '/opt/mora02/docs/pilot/html/',
    }
    return {
        "success": True,
        "filename": filename,
        "download_url": f"{NGINX_DOWNLOADS_URL}/{filename}",
        "move_command": f"mv ~/Downloads/{filename} {targets.get(ext, '/opt/mora02/docs/')}"
    }

@app.get("/list-downloads")
async def list_downloads():
    files = []
    for f in sorted(DOWNLOADS_DIR.glob("*")):
        if f.is_file():
            files.append({
                "filename": f.name,
                "download_url": f"{NGINX_DOWNLOADS_URL}/{f.name}",
                "size": f.stat().st_size
            })
    return {"success": True, "files": files}

# ============================================================================
# ENDPOINTS - LLM PROFILE SWITCHER
# ============================================================================
# Talks to the host-side systemd switcher via /llm-switch/ bind mount.
# Script-Runner has NO docker daemon access — the switch itself runs on the
# host, triggered by file-drop into /llm-switch/requests/.

from mora02_core.llm import (
    LLMSwitchError,
    get_current_profile as llm_get_current,
    get_switch_status as llm_get_status,
    list_profiles as llm_list_profiles,
    profile_names as llm_valid_profile_names,
    submit_switch as llm_submit_switch,
    switch_profile_blocking as llm_switch_blocking,
)


class LLMSwitchRequest(BaseModel):
    profile: str


@app.get("/llm/profiles")
async def get_llm_profiles():
    """List all available LLM profiles with metadata and the current one."""
    return {
        "profiles": llm_list_profiles(),
        "current": llm_get_current(),
    }


@app.get("/llm/current")
async def get_llm_current():
    """Return just the currently active LLM profile, or null if unknown."""
    return {"current": llm_get_current()}


@app.post("/llm/switch")
async def post_llm_switch(request: LLMSwitchRequest):
    """
    Submit a switch request. Returns immediately with a request_id.
    Poll GET /llm/switch/{request_id} for the result.
    """
    if request.profile not in llm_valid_profile_names():
        raise HTTPException(
            status_code=400,
            detail=f"invalid profile: {request.profile}"
        )
    try:
        request_id = llm_submit_switch(request.profile)
        return {
            "success": True,
            "request_id": request_id,
            "status": "pending",
            "profile": request.profile,
        }
    except LLMSwitchError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/llm/switch/{request_id}")
async def get_llm_switch_status(request_id: str):
    """
    Poll for the result of a switch request. Returns {"status":"pending"}
    while the host service is still working, or the full result when done.
    """
    try:
        result = llm_get_status(request_id)
    except LLMSwitchError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if result is None:
        return {"status": "pending", "request_id": request_id}
    return {"status": "done", "request_id": request_id, "result": result}


# ============================================================================
# ENDPOINTS - GPU MEMORY RELEASE
# ============================================================================
# Soft-release of VRAM from other GPU-using containers on the mora02-net.
# For now: ComfyUI only (it is the primary culprit for VRAM conflicts).
# ComfyUI's native POST /free unloads all models without stopping the server,
# so the container stays up and the next request will lazy-reload.
# Ollama auto-unloads via idle timeout and is skipped here.

COMFYUI_INTERNAL_URL = "http://comfyui:8188"


@app.post("/vram/free")
async def free_vram():
    """Release VRAM from GPU-using companion containers (ComfyUI)."""
    results: dict = {}

    # ComfyUI soft release
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{COMFYUI_INTERNAL_URL}/free",
                json={"unload_models": True, "free_memory": True},
            )
            if resp.status_code < 400:
                results["comfyui"] = {"ok": True, "status": resp.status_code, "message": "released"}
            else:
                results["comfyui"] = {
                    "ok": False,
                    "status": resp.status_code,
                    "message": resp.text[:200],
                }
    except httpx.ConnectError:
        results["comfyui"] = {"ok": False, "message": "comfyui unreachable (container down?)"}
    except Exception as e:
        results["comfyui"] = {"ok": False, "message": f"error: {e}"}

    any_ok = any(r.get("ok") for r in results.values())
    return {"success": any_ok, "results": results}
