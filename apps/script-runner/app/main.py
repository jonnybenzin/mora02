#!/usr/bin/env python3
"""
Mora02 Script Runner API
FastAPI service for gifer, clipper, typer scripts
"""

import asyncio
from functools import partial
import json
import subprocess
import uuid
import os
import re
import time
import shutil
import httpx
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, List, Optional
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from mora02_core import assets as asset_refs
from mora02_core._common import segment_problem
from mora02_core.comfyui import (
    generate_images,
    generate_music,
    generate_video,
    upscale_image,
    expand_image,
    upload_image_url_to_comfyui,
    edit_image,
    cutout_image,
    erase_image,
    facefix_image,
)
from mora02_core.media import MediaError, create_clip, create_gif, create_text_frame
from mora02_core.pipeline import run_pipeline, run_pipeline_spec, rerun_pipeline_spec, resume_pipeline, PipelineError, spec as pipeline_spec, vocab as pipeline_vocab, runlog as pipeline_runlog

# The agent layer keeps its endpoints in their own module (see agents.py).
from agents import router as agents_router
# ...and its MCP surface in another: /mcp is a protocol, not an endpoint, and
# the tools it exposes are deliberately fewer than the routes below.
from mcp_tools import router as mcp_router
from speech import router as speech_router
from steps import router as steps_router

from runtime import (  # noqa: F401  (re-exported: the endpoints below use them)
    DATA_DIR, FINAL_DIR, HOST_DATA_PATH, NGINX_BASE_URL, PEXELS_API_KEY,
    PIXABAY_API_KEY, SERVICE_VERSION, WIP_DIR, _checked_run_id, _docker_cli,
    _FLOW_NAME_RE, _log, _media_type, _segment_problem, _SESSION_ID_RE,
    container_to_host_path, create_baserow_entry, create_session,
    create_timestamp, get_nginx_url, get_session_dir, inside, safe_segment,
    step_out_path, step_segment,
)

# ============================================================================
# APP SETUP
# ============================================================================

app = FastAPI(
    title="Mora02 Script Runner",
    description="API for gifer, clipper, typer scripts",
    version=SERVICE_VERSION,
)

app.include_router(agents_router)
app.include_router(mcp_router)
app.include_router(speech_router)
app.include_router(steps_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# MODELS
# ============================================================================

class GiferRequest(BaseModel):
    session_id: str
    durations: str  # e.g. "1,2,2,4" in seconds
    quality: str = "medium"  # low, medium, high, ultra
    size: Optional[str] = None  # e.g. "800x600" or "800"

class TyperRequest(BaseModel):
    session_id: str  # Required for multi-slide support
    text: str
    size: str = "1080x1080"
    template: str = "light"  # dark, darker, light, black
    font: str = "bold"  # bold, bold-italic, thin, thin-italic
    fontsize: str = "large"  # small, medium, large or pixel value
    layout: str = "left"  # left, centered

class ClipperRequest(BaseModel):
    session_id: str
    resolution: str = "1080p"
    durations: str = "4"  # seconds per image
    animation: str = "pan"  # pan, zoom_in, zoom_out, none
    direction: str = "90"  # 0-360 degrees
    intensity: str = "20"
    transition: str = "1"  # seconds
class FinalizeSessionRequest(BaseModel):
    session_id: str
    script_type: str  # gifer, clipper, typer

class SessionResponse(BaseModel):
    session_id: str
    message: str

class RunResponse(BaseModel):
    success: bool
    filename: Optional[str] = None
    preview_url: Optional[str] = None
    slide_number: Optional[int] = None
    error: Optional[str] = None
class StockSearchRequest(BaseModel):
    query: str
    count: int = 5  # Number of results to return
    orientation: str = "landscape"  # landscape, portrait, square

class StockDownloadRequest(BaseModel):
    source: str  # pexels, pixabay
    image_url: str
    image_id: str
    photographer: Optional[str] = None

# ============================================================================
# ENDPOINTS - SESSION MANAGEMENT
# ============================================================================

@app.post("/session/create", response_model=SessionResponse)
async def create_new_session():
    """Create a new session for file uploads"""
    session_id = create_session()
    return SessionResponse(
        session_id=session_id,
        message=f"Session created. Upload files to /upload/{session_id}"
    )

@app.post("/upload/{session_id}")
async def upload_files(session_id: str, files: List[UploadFile] = File(...)):
    """Upload files to session input directory"""
    session_dir = get_session_dir(session_id)
    input_dir = session_dir / "input"
    
    uploaded = []
    for idx, file in enumerate(files, 1):
        # Prefix with number for ordering
        filename = f"{idx:02d}-{file.filename}"
        filepath = input_dir / filename
        
        with open(filepath, "wb") as f:
            content = await file.read()
            f.write(content)
        
        uploaded.append(filename)
    
    return {
        "session_id": session_id,
        "uploaded": uploaded,
        "count": len(uploaded)
    }

@app.get("/session/{session_id}/files")
async def list_session_files(session_id: str):
    """List files in session"""
    session_dir = get_session_dir(session_id)
    
    input_files = sorted([f.name for f in (session_dir / "input").glob("*") if f.is_file()])
    output_files = sorted([f.name for f in (session_dir / "output").glob("*") if f.is_file()])
    
    return {
        "session_id": session_id,
        "input": input_files,
        "output": output_files
    }

@app.delete("/session/{session_id}")
async def delete_session(session_id: str):
    """Delete session and all its files"""
    session_dir = get_session_dir(session_id)
    await asyncio.to_thread(shutil.rmtree, session_dir)
    return {"message": f"Session {session_id} deleted"}

# ============================================================================
# ENDPOINTS - GIFER
# ============================================================================

@app.post("/run/gifer", response_model=RunResponse)
async def run_gifer(request: GiferRequest):
    """Run gifer script to create GIF from uploaded images"""
    session_dir = get_session_dir(request.session_id)
    input_dir = session_dir / "input"
    output_dir = session_dir / "output"
    
    # Check for input files
    input_files = sorted(input_dir.glob("*"))
    image_files = [f for f in input_files if f.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp', '.bmp')]
    
    if not image_files:
        return RunResponse(success=False, error="No images found in session")
    
    # Generate filename: gif_YYMMDD-HHMM_NNN.gif
    timestamp = create_timestamp()
    existing = len(list(output_dir.glob("gif_*.gif")))
    counter = existing + 1
    output_file = output_dir / f"gif_{timestamp}_{counter:03d}.gif"
    
    try:
        from mora02_core.media import create_gif, MediaError

        try:
            # In a thread: this is ffmpeg, and the single uvicorn loop it would
            # otherwise sit on is the one serving the Pilot's polling, the
            # MCP surface during an agent turn, and every pipeline step
            # running beside it. The pipeline twin of this call already did
            # it this way (review 3, 2026-09-04).
            await asyncio.to_thread(
                partial(create_gif,
                    input_files=image_files,
                    output_path=output_file,
                    durations=request.durations,
                    quality=request.quality,
                    size=request.size,
                    ))
        except MediaError as e:
            return RunResponse(success=False, error=str(e))

        preview_url = f"/preview/{request.session_id}/{output_file.name}"
        return RunResponse(
            success=True,
            filename=output_file.name,
            preview_url=preview_url,
        )

    except Exception as e:
        return RunResponse(success=False, error=str(e))

# ============================================================================
# ENDPOINTS - TYPER (Multi-Slide Support)
# ============================================================================

@app.post("/run/typer", response_model=RunResponse)
async def run_typer(request: TyperRequest):
    """Run typer script to create text frame PNG - supports multiple slides per session"""
    session_dir = get_session_dir(request.session_id)
    output_dir = session_dir / "output"
    
    # Count existing slides to determine next number
    existing_slides = sorted(output_dir.glob("*.png"))
    slide_num = len(existing_slides) + 1

    # Generate filename: img_YYMMDD-HHMM_NNN.png
    timestamp = create_timestamp()
    output_file = output_dir / f"img_{timestamp}_{slide_num:03d}.png"
    
    try:
        from mora02_core.media import create_text_frame, MediaError

        try:
            # In a thread: this is ffmpeg, and the single uvicorn loop it would
            # otherwise sit on is the one serving the Pilot's polling, the
            # MCP surface during an agent turn, and every pipeline step
            # running beside it. The pipeline twin of this call already did
            # it this way (review 3, 2026-09-04).
            await asyncio.to_thread(
                partial(create_text_frame,
                    text=request.text,
                    output_path=output_file,
                    size=request.size,
                    template=request.template,
                    font=request.font,
                    fontsize=request.fontsize,
                    layout=request.layout,
                    ))
        except MediaError as e:
            return RunResponse(success=False, error=str(e))

        preview_url = f"/preview/{request.session_id}/{output_file.name}"
        return RunResponse(
            success=True,
            filename=output_file.name,
            preview_url=preview_url,
            slide_number=slide_num,
        )

    except Exception as e:
        return RunResponse(success=False, error=str(e))

# ============================================================================
# ENDPOINTS - CLIPPER
# ============================================================================

@app.post("/run/clipper", response_model=RunResponse)
async def run_clipper(request: ClipperRequest):
    """Run clipper script to create video from images"""
    session_dir = get_session_dir(request.session_id)
    input_dir = session_dir / "input"
    output_dir = session_dir / "output"
    
    # Check for input files
    input_files = sorted(input_dir.glob("*"))
    media_files = [f for f in input_files if f.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp', '.bmp', '.mp4', '.mov', '.webm', '.avi', '.mkv')]
    
    if not media_files:
        return RunResponse(success=False, error="No media files found in session")
    
    # Generate filename: clip_YYMMDD-HHMM_NNN.mp4
    timestamp = create_timestamp()
    existing = len(list(output_dir.glob("clip_*.mp4")))
    counter = existing + 1
    output_file = output_dir / f"clip_{timestamp}_{counter:03d}.mp4"
    
    try:
        from mora02_core.media import create_clip, MediaError

        try:
            # In a thread: this is ffmpeg, and the single uvicorn loop it would
            # otherwise sit on is the one serving the Pilot's polling, the
            # MCP surface during an agent turn, and every pipeline step
            # running beside it. The pipeline twin of this call already did
            # it this way (review 3, 2026-09-04).
            await asyncio.to_thread(
                partial(create_clip,
                    input_files=media_files,
                    output_path=output_file,
                    resolution=request.resolution,
                    durations=request.durations,
                    animation=request.animation,
                    direction=request.direction,
                    intensity=request.intensity,
                    transition=request.transition,
                    ))
        except MediaError as e:
            return RunResponse(success=False, error=str(e))

        preview_url = f"/preview/{request.session_id}/{output_file.name}"
        return RunResponse(
            success=True,
            filename=output_file.name,
            preview_url=preview_url,
        )

    except Exception as e:
        return RunResponse(success=False, error=str(e))

# ============================================================================
# ENDPOINTS - PREVIEW & FINALIZE
# ============================================================================

@app.get("/preview/{session_id}/{filename}")
async def get_preview(session_id: str, filename: str):
    """Serve preview file from session output"""
    session_dir = get_session_dir(session_id)
    filepath = session_dir / "output" / filename
    
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="File not found")
    
    suffix = filepath.suffix.lower()
    media_type = _media_type(suffix)
    
    return FileResponse(filepath, media_type=media_type)

@app.post("/finalize-session")
async def finalize_session(request: FinalizeSessionRequest):
    """
    Finalize entire session - creates timestamped folder with all outputs.
    For gifer/clipper: also copies sourcefiles.
    For typer: copies all slides.
    Also creates entry in Baserow.
    """
    session_dir = get_session_dir(request.session_id)
    input_dir = session_dir / "input"
    output_dir = session_dir / "output"
    
    # Check for output files
    output_files = sorted(output_dir.glob("*"))
    if not output_files:
        return {"success": False, "error": "No output files in session"}
    
    # Generate timestamp folder name
    timestamp = create_timestamp()
    session_short = request.session_id.split("_")[-1][:6] if "_" in request.session_id else request.session_id[:6]
    folder_name = f"{timestamp}_{session_short}"
    
    # Create final directory. The channel is a caller-supplied segment, and
    # this path is created and then written into -- the same class as
    # /publish-asset, which validates its target against a known list.
    final_path = inside(
        FINAL_DIR,
        FINAL_DIR / safe_segment(request.script_type, "script_type") / folder_name,
        "script_type",
    )
    final_path.mkdir(parents=True, exist_ok=True)
    
    # In a thread: these are finished clips and GIFs, tens of megabytes, and
    # every byte was copied on the event loop that also serves the Pilot's chat
    # and any pipeline running beside it (review 3, 2026-09-04).
    def _copy_out() -> tuple[list, list]:
        copied, sources = [], []
        for f in output_files:
            if f.is_file():
                shutil.copy2(f, final_path / f.name)
                copied.append(f.name)
        if request.script_type in ["gifer", "clipper"] and input_dir.exists():
            sourcefiles_path = final_path / "sourcefiles"
            sourcefiles_path.mkdir(exist_ok=True)
            for f in sorted(input_dir.glob("*")):
                if f.is_file():
                    shutil.copy2(f, sourcefiles_path / f.name)
                    sources.append(f.name)
        return copied, sources

    copied_files, sourcefiles = await asyncio.to_thread(_copy_out)
    
    # Convert to host path
    host_path = container_to_host_path(str(final_path))
    
    # Build nginx preview URL
    first_file = copied_files[0] if copied_files else ""
    preview_url = get_nginx_url(request.script_type, folder_name, first_file)
    
    # Create Baserow entry
    baserow_result = await create_baserow_entry(
        script_type=request.script_type,
        folder=folder_name,
        files=copied_files,
        host_path=host_path
    )
    
    # Cleanup wip folder
    await asyncio.to_thread(shutil.rmtree, session_dir)
    
    return {
        "success": True,
        "path": host_path,
        "folder": folder_name,
        "files": copied_files,
        "sourcefiles": sourcefiles,
        "preview_url": preview_url,
        "script_type": request.script_type,
        "baserow_entry": baserow_result is not None
    }





# ============================================================================
# STOCK PHOTO SEARCH (Pexels & Pixabay)
# ============================================================================

@app.post("/search/pexels")
async def search_pexels(request: StockSearchRequest):
    """Search Pexels for images"""
    import urllib.parse
    
    url = f"https://api.pexels.com/v1/search?query={urllib.parse.quote(request.query)}&per_page={request.count}&orientation={request.orientation}"
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers={"Authorization": PEXELS_API_KEY},
                timeout=10.0
            )
            response.raise_for_status()
            data = response.json()
            
            results = []
            for photo in data.get('photos', []):
                results.append({
                    'id': str(photo['id']),
                    'thumbnail': photo['src'].get('medium', photo['src'].get('small')),
                    'url': photo['src'].get('original', photo['src'].get('large2x')),
                    'photographer': photo.get('photographer', 'Unknown'),
                    'width': photo.get('width'),
                    'height': photo.get('height')
                })
            
            return {
                "success": True,
                "source": "pexels",
                "query": request.query,
                "count": len(results),
                "results": results
            }
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/search/pixabay")
async def search_pixabay(request: StockSearchRequest):
    """Search Pixabay for images"""
    import urllib.parse
    
    orientation_map = {"landscape": "horizontal", "portrait": "vertical", "square": "all"}
    orientation = orientation_map.get(request.orientation, "horizontal")
    
    url = f"https://pixabay.com/api/?key={PIXABAY_API_KEY}&q={urllib.parse.quote(request.query)}&per_page={request.count}&orientation={orientation}&image_type=photo&safesearch=true"
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=10.0)
            response.raise_for_status()
            data = response.json()
            
            results = []
            for hit in data.get('hits', []):
                # Try fullHDURL (1920px) first, fallback to largeImageURL (1280px)
                image_url = hit.get('fullHDURL') or hit.get('largeImageURL') or hit.get('webformatURL')
                results.append({
                    'id': str(hit['id']),
                    'thumbnail': hit.get('webformatURL', hit.get('previewURL')),
                    'url': image_url,
                    'photographer': hit.get('user', 'Unknown'),
                    'width': hit.get('imageWidth'),
                    'height': hit.get('imageHeight')
                })
            
            return {
                "success": True,
                "source": "pixabay",
                "query": request.query,
                "count": len(results),
                "results": results
            }
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/download/stock")
async def download_stock_image(request: StockDownloadRequest):
    """Download a stock image and save to final directory"""
    # Checked before the fetch, not after it: these two become the folder and
    # the file name, and a request that cannot be stored should not cost a
    # download first.
    src = safe_segment(request.source, "source")
    img_id = safe_segment(request.image_id, "image_id")

    try:
        # Download image
        async with httpx.AsyncClient() as client:
            response = await client.get(
                request.image_url,
                headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"},
                timeout=30.0,
                follow_redirects=True
            )
            response.raise_for_status()
            image_data = response.content
        
        # Determine extension
        content_type = response.headers.get('content-type', '')
        if 'png' in content_type:
            ext = '.png'
        elif 'webp' in content_type:
            ext = '.webp'
        else:
            ext = '.jpg'
        
        # Create filename and folder: img_YYMMDD-HHMM_source_id.ext
        timestamp = create_timestamp()
        folder_name = f"img_{timestamp}_{src}_{img_id}"
        filename = f"img_{timestamp}_{src}_{img_id}{ext}"

        # Save to final directory
        final_path = inside(FINAL_DIR, FINAL_DIR / src / folder_name, "source")
        final_path.mkdir(parents=True, exist_ok=True)
        
        filepath = final_path / filename
        with open(filepath, 'wb') as f:
            f.write(image_data)
        
        # Convert to host path
        host_path = container_to_host_path(str(final_path))
        preview_url = f"{NGINX_BASE_URL}/{request.source}/{folder_name}/{filename}"
        
        # Create Baserow entry
        await create_baserow_entry(
            script_type=request.source,
            folder=folder_name,
            files=[filename],
            host_path=host_path
        )
        
        return {
            "success": True,
            "source": request.source,
            "filename": filename,
            "path": host_path,
            "preview_url": preview_url,
            "photographer": request.photographer
        }

    except HTTPException:
        # A refused request is not a failed download. Without this the catch-all
        # below turns a 422 into HTTP 200 with success=false, and a caller that
        # reads the status cannot tell a rejection from a success.
        raise
    except Exception as e:
        return {"success": False, "error": str(e)}

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


# ============================================================================
# ENDPOINTS - PIPELINE (HITL via Lobster)
# ============================================================================
# Relay for the headless HITL pipeline runtime (ADR-022). script-runner holds the
# docker socket (ADR-020), so it is the executor: it calls mora02_core.pipeline,
# which runs `docker exec mora02-openclaw lobster run|resume`. Pilot stays
# socket-free and drives HITL by calling these routes — run a skill, then resume
# it once a human decides in the Pilot inbox.

class PipelineRunRequest(BaseModel):
    pipeline_path: str            # container path to the .lobster workflow file
    args: Optional[dict] = None   # optional --args-json payload
    runner: Optional[str] = None  # override MORA02_PIPELINE_RUNNER (default lobster)


class PipelineRerunRequest(BaseModel):
    """Re-run only what a change made stale, replaying the rest of an earlier run."""
    source_run_id: str              # the run whose stored outputs get replayed
    changed: list[str]              # compiled step ids the user touched
    overrides: Optional[dict] = None  # {step_id: {param: value}} applied before compiling
    spec: Optional[dict] = None     # a spec that may DIFFER from the one that ran
    args: Optional[dict] = None
    runner: Optional[str] = None


class PipelineResumeRequest(BaseModel):
    token: str                      # resumeToken handed back by a paused run
    response: Optional[dict] = None # structured answer for an input: gate
    approve: Optional[bool] = None  # yes/no for an approval: gate
    cancel: bool = False            # cancel the workflow instead of continuing
    runner: Optional[str] = None
    background: bool = False        # fire-and-forget: resume runs the (possibly long)
                                    # remaining tail without blocking the HTTP call
    run_id: Optional[str] = None    # the run this decision belongs to, so it lands in
                                    # the run log (the resume token does not carry it)


def _recover_run_spec(source_run_id: str) -> dict:
    """The spec a past run recorded, or a 404/409 saying which is missing.

    Two endpoints did this lookup and told the two failures apart differently:
    /pipeline/rerun distinguished "there is no such run" from "the run predates
    spec recording", /pipeline/rerun-plan collapsed both into the second — so a
    typo'd run id was diagnosed as an old run (review 3, 2026-09-04).
    """
    events = pipeline_runlog.read_events(_checked_run_id(source_run_id, "source_run_id"))
    start = next((e for e in events if e.get("kind") == "run_start"), None)
    if start is None:
        raise HTTPException(status_code=404, detail=f"no run log for {source_run_id!r}")
    spec = start.get("spec")
    if spec is None:
        raise HTTPException(
            status_code=409,
            detail=f"run {source_run_id!r} predates spec recording — "
                   "pass 'spec' explicitly to re-run it",
        )
    return spec


def _pipeline_result_to_dict(res) -> dict:
    """Flatten a PipelineResult for the JSON response (Pilot reads this verbatim).

    The shape lives on the dataclass; this name stays because six call sites
    use it.
    """
    return res.to_dict()


@app.post("/pipeline/run")
async def pipeline_run(req: PipelineRunRequest):
    """Start a HITL workflow headlessly. May pause at a gate (status needs_input)."""
    if not req.pipeline_path.endswith(".lobster"):
        raise HTTPException(status_code=400, detail="pipeline_path must be a .lobster file")
    try:
        res = await run_pipeline(req.pipeline_path, args=req.args, runner=req.runner)
    except PipelineError as e:
        # Transport failure (runner unreachable / no envelope) — not a workflow error.
        raise HTTPException(status_code=502, detail=f"pipeline runner error: {e}")
    return _pipeline_result_to_dict(res)


class PipelineRunSpecRequest(BaseModel):
    name: Optional[str] = None    # a tracked spec under pipelines/specs/ (no extension needed)
    spec: Optional[dict] = None   # an inline spec dict (e.g. from an authoring front-end)
    args: Optional[dict] = None   # variable inputs for the run
    runner: Optional[str] = None


# Where named specs live (host pipelines/specs/ via the pipelines mount).
# Where named specs live. Read through the library so the four readers of this
# directory agree, and so a test can point it somewhere without knowing which
# module happens to hold the constant (review 3, 2026-09-04).
_PIPELINE_SPECS_DIR = pipeline_spec.specs_dir()


@app.post("/pipeline/run-spec")
async def pipeline_run_spec(req: PipelineRunSpecRequest):
    """Compile a mora02 pipeline spec to .lobster and run it (may pause at a gate).

    Pass exactly one of: ``spec`` (an inline spec dict) or ``name`` (a tracked spec
    file in pipelines/specs/, with or without extension). This is the trigger that
    drives the whole spec → compile → run → run-log chain; the compiled .lobster is
    written to the OpenClaw workspace and left for inspection.
    """
    if req.spec is not None:
        # Second door for the same rule as on save: write the implicit wiring
        # down. The builder runs the editor's stack WITHOUT saving it first, so
        # materialising only on save would leave the commonest path implicit -
        # and the spec recorded in the run log (which a partial re-run later
        # reads back) would not say what actually ran. Resolution is unchanged;
        # only the silence goes.
        target = pipeline_spec.materialize_wiring(req.spec)
    elif req.name:
        # The same pattern the flow-library endpoints apply to a name before
        # they build a path from it. This sibling did not, so a name with `..`
        # in it chose which spec file to compile AND RUN (review 3).
        stem = req.name[:-len(Path(req.name).suffix)] if Path(req.name).suffix else req.name
        if not _FLOW_NAME_RE.fullmatch(stem):
            raise HTTPException(status_code=422, detail=f"name: {req.name!r} is not a flow name")
        found = pipeline_spec.resolve_spec_path(req.name)
        match = str(found) if found else None
        if match is None:
            raise HTTPException(
                status_code=404,
                detail=f"no spec named {req.name!r} in {_PIPELINE_SPECS_DIR}",
            )
        target = match
    else:
        raise HTTPException(status_code=400, detail="provide either 'spec' (inline) or 'name'")

    try:
        res = await run_pipeline_spec(target, args=req.args, runner=req.runner)
    except PipelineError as e:
        # Covers compile errors (bad spec / unknown or planned op) and runner transport.
        raise HTTPException(status_code=400, detail=f"pipeline spec error: {e}")
    return _pipeline_result_to_dict(res)


@app.post("/pipeline/rerun")
async def pipeline_rerun(req: PipelineRerunRequest):
    """Re-run a flow partially: recompute what changed, replay the rest.

    Without ``spec`` the one the source run RECORDED is used — not the library
    file, which may have been edited since, and which never existed for a flow
    sent straight from the builder. Passing ``spec`` explicitly is what makes a
    revision possible: hand in a spec with an extra edit step and the unchanged
    parts still come from the earlier run.
    """
    spec = req.spec
    if spec is None:
        spec = await asyncio.to_thread(_recover_run_spec, req.source_run_id)
    try:
        res = await rerun_pipeline_spec(
            spec, source_run_id=req.source_run_id, changed=req.changed,
            overrides=req.overrides, args=req.args, runner=req.runner,
        )
    except PipelineError as e:
        raise HTTPException(status_code=400, detail=f"pipeline rerun error: {e}")
    return _pipeline_result_to_dict(res)


@app.post("/pipeline/rerun-plan")
async def pipeline_rerun_plan(req: PipelineRerunRequest):
    """What a re-run WOULD do — same inputs, nothing executed.

    The honest thing to show before spending GPU minutes: which steps come back
    from the earlier run, which are recomputed, and which approvals stand.
    """
    spec = req.spec
    if spec is None:
        spec = await asyncio.to_thread(_recover_run_spec, req.source_run_id)
    try:
        plan = pipeline_spec.plan_rerun(spec, req.changed)
    except PipelineError as e:
        raise HTTPException(status_code=400, detail=f"invalid spec: {e}")
    return {
        "redo": plan.redo,
        "reuse": plan.reuse,
        "gates_needed": plan.gates_needed,
        "saved_steps": len(plan.reuse),
    }


@app.get("/pipeline/flows")
async def pipeline_flows():
    """The flow LIBRARY — the named flows under pipelines/specs/.

    Each entry is a saved pipeline spec (name + steps). Consumed by the /flow
    authoring tool to offer a picker and to load a flow by name.
    """
    flows = [
        {
            "name": data.get("name") or path.stem,
            "file": path.stem,
            "description": data.get("description", ""),
            "tags": data.get("tags", []),
            "updated": data.get("updated", ""),
            "steps": len(data.get("steps", [])),
        }
        for path, data in await asyncio.to_thread(pipeline_spec.list_specs)
    ]
    return {"flows": flows}


@app.get("/pipeline/flow/{name}")
async def pipeline_flow(name: str):
    """Return one named flow spec (matched by spec name or filename stem)."""
    specs = pipeline_spec.specs_dir()
    if specs.is_dir():
        for p in specs.glob("*.json"):
            try:
                spec = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if spec.get("name") == name or p.stem == name:
                return spec
    raise HTTPException(status_code=404, detail=f"flow {name!r} not found")


# A flow name doubles as its file name, so it has to survive both a file system
# and a URL. The authoring UI slugifies before it posts; this is the guard for
# every other caller.


@app.post("/pipeline/flow/{name}")
async def pipeline_flow_save(name: str, request: Request, overwrite: bool = False):
    """Save an authored flow to pipelines/specs/<name>.json.

    Body = the whole spec: metadata (description, tags) plus steps. It is parsed
    and checked against the vocabulary BEFORE anything touches disk, so the
    library can never hold a flow that fails to load back.

    Ops with status "planned" are allowed here on purpose — a flow may be
    authored ahead of its handler; compiling it is what refuses to run.
    """
    if not _FLOW_NAME_RE.fullmatch(name):
        raise HTTPException(
            status_code=400,
            detail="flow name must be 2-64 chars of lowercase letters, digits and dashes",
        )
    try:
        data = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="body must be JSON")
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="spec must be a JSON object")

    # The URL is the authority — it keeps file name and spec name from drifting.
    data["name"] = name
    try:
        parsed = pipeline_spec.load_spec(data)
    except PipelineError as e:
        raise HTTPException(status_code=422, detail=f"invalid spec: {e}")

    # A reference forward or into nothing can never become valid, so the library
    # refuses it here rather than letting the flow sit there until someone runs
    # it. Ops with status "planned" stay allowed - authoring ahead of a handler
    # is intended; wiring to a step that does not exist is not.
    try:
        pipeline_spec.check_references(parsed)
        pipeline_spec.check_wire_types(parsed)
    except PipelineError as e:
        raise HTTPException(status_code=422, detail=f"invalid wiring: {e}")

    known = pipeline_vocab.op_names()
    unknown = sorted({s.op for s in parsed.steps if isinstance(s, pipeline_spec.OpStep)} - known)
    if unknown:
        raise HTTPException(
            status_code=422, detail=f"unknown ops: {', '.join(unknown)}"
        )

    # Write the implicit wiring down before it reaches disk. A step without `in:`
    # takes the previous step's output, which is invisible in the file and in the
    # builder - fine in a straight chain, silently wrong the moment a flow has two
    # branches. Saving is the right moment: the default keeps working, and what
    # runs is what the file says.
    data = pipeline_spec.materialize_wiring(data)

    data.setdefault("description", "")
    data.setdefault("tags", [])
    data["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    specs = pipeline_spec.specs_dir()
    specs.mkdir(parents=True, exist_ok=True)
    target = specs / f"{name}.json"
    existed = target.exists()
    if existed and not overwrite:
        raise HTTPException(
            status_code=409,
            detail=f"flow {name!r} already exists — pass ?overwrite=true to replace it",
        )
    # Write through a temp file so a crash mid-write cannot leave a half spec
    # that the library endpoint would then skip as unparsable.
    tmp = target.with_name(f".{name}.json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, target)
    # This runs as root inside the container, so a fresh file would land as
    # root:root in the repo checkout and break `git checkout` on the host.
    # Hand it to whoever owns the directory — portable, no uid in config.
    try:
        st = specs.stat()
        os.chown(target, st.st_uid, st.st_gid)
        os.chmod(target, 0o664)
    except OSError:
        pass
    _log.info("flow saved: %s (%d steps, overwrite=%s)", name, len(parsed.steps), existed)
    return {
        "ok": True,
        "name": name,
        "file": target.name,
        "steps": len(parsed.steps),
        "replaced": existed,
        "updated": data["updated"],
    }


@app.delete("/pipeline/flow/{name}")
async def pipeline_flow_delete(name: str):
    """Delete a saved flow.

    The same name rule as the save endpoint guards this one: it allows no dots
    and no slashes, so a traversal like ``../../etc/x`` is rejected before any
    path is built. The authoring UI asks the human first; this endpoint does not.
    """
    if not _FLOW_NAME_RE.fullmatch(name):
        raise HTTPException(
            status_code=400,
            detail="flow name must be 2-64 chars of lowercase letters, digits and dashes",
        )
    target = pipeline_spec.specs_dir() / f"{name}.json"
    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"flow {name!r} not found")
    try:
        target.unlink()
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"could not delete: {e}")
    _log.info("flow deleted: %s", name)
    return {"ok": True, "name": name, "deleted": True}


def _read_run_events(run_id: str):
    """Parse a run's JSONL log into a list of events, or None if it doesn't exist."""
    path = os.path.join(pipeline_runlog.log_dir(), f"{run_id}.jsonl")
    events = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    events.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        return None
    return events


@app.get("/pipeline/runs")
async def pipeline_runs():
    """List recent pipeline runs (newest first) for the Runs view — a summary per run."""
    d = pipeline_runlog.log_dir()
    runs = []

    def _scan() -> list:
        try:
            return sorted(Path(d).glob("*.jsonl"),
                          key=lambda p: p.stat().st_mtime, reverse=True)[:40]
        except OSError:
            return []

    files = await asyncio.to_thread(_scan)
    for p in files:
        events = await asyncio.to_thread(_read_run_events, p.stem) or []
        start = next((e for e in events if e.get("kind") == "run_start"), {})
        steps = [e for e in events if e.get("kind") == "step"]
        result = next((e for e in reversed(events) if e.get("kind") == "run_result"), None)
        last = steps[-1] if steps else None
        try:
            active = (time.time() - p.stat().st_mtime) < 90  # log touched recently
        except OSError:
            active = False
        runs.append({
            "run_id": p.stem,
            "pipeline": start.get("pipeline") or p.stem,
            "args": start.get("args"),
            "ts": start.get("ts"),
            "steps_done": len(steps),
            "last_op": last.get("op") if last else None,
            "last_status": last.get("status") if last else None,
            "failed": any(s.get("status") == "failed" for s in steps),
            "active": active,
            "result": result.get("status") if result else None,
        })
    return {"runs": runs}


# Structural log fields, already mapped above or too bulky for the view: inputs
# and params can carry whole prompts, and the view has its own place for them.
_RUN_VIEW_SKIP = {"kind", "inputs", "params", "out_name"}


@app.get("/pipeline/run/{run_id}")
async def pipeline_run_detail(run_id: str):
    """Full step-by-step detail of one run (for the live Runs view)."""
    # In a thread: the Runs view polls this every three seconds for as long as
    # a run looks alive — which is exactly the window in which this same loop is
    # driving that run's steps. Reading and parsing a growing log file on it
    # competed with the work it was reporting on (review 3, 2026-09-04).
    events = await asyncio.to_thread(_read_run_events, os.path.basename(run_id))
    if events is None:
        raise HTTPException(status_code=404, detail=f"run {run_id!r} not found")
    start = next((e for e in events if e.get("kind") == "run_start"), {})
    result = next((e for e in reversed(events) if e.get("kind") == "run_result"), None)
    steps = []
    for e in events:
        if e.get("kind") != "step":
            continue
        out = e.get("out")
        url = None
        if isinstance(out, str) and out.startswith("asset://"):
            try:
                url = asset_refs.url_for_ref(out)
            except Exception:
                url = None
        entry = {
            "step_id": e.get("step_id"), "op": e.get("op"), "status": e.get("status"),
            "out": out, "out_type": e.get("out_type"), "url": url, "error": e.get("error"),
        }
        # Pass the handler's own "log" fields through - token counts, model name,
        # the truncation flag and its hint. The view renders them (runs.js reads
        # s.truncated, s.hint, s.tokens_out); without this they never left the
        # log file, so a completion cut at max_tokens looked like a whole one.
        # Generic on purpose: a new op attaching a new field needs no change here.
        entry.update({k: v for k, v in e.items()
                      if k not in entry and k not in _RUN_VIEW_SKIP})
        steps.append(entry)
    return {
        "run_id": run_id,
        "pipeline": start.get("pipeline"),
        "args": start.get("args"),
        "ts": start.get("ts"),
        "steps": steps,
        "result": result.get("status") if result else None,
    }


_bg_resume_tasks: set = set()  # keep detached resume tasks referenced until done
_PILOT_URL = os.environ.get("PILOT_URL", "http://pilot:8098")


async def _bg_resume_and_refile(req: "PipelineResumeRequest") -> None:
    """Run a detached resume; if it pauses again at a further gate, ask Pilot to
    re-file that decision into the HITL inbox so multi-gate flows keep working."""
    try:
        res = await resume_pipeline(
            req.token, response=req.response, approve=req.approve,
            cancel=req.cancel, runner=req.runner, run_id=req.run_id,
        )
    except Exception as e:
        # The caller was told "resuming" before any of this was attempted, and
        # the Pilot cleared the inbox item on that answer. So a failure here is
        # invisible everywhere: no inbox item, no HTTP error, and — until now —
        # nothing in the run log either, so the RUNS view showed a flow that
        # simply stops after its last step (review 3, 2026-09-04). The run log
        # is where a run's fate belongs, so that is where this goes.
        _log.exception("background resume failed")
        pipeline_runlog.log_event(
            req.run_id, "run_result", ok=False, status="failed",
            error=f"background resume failed: {e}",
        )
        return
    d = _pipeline_result_to_dict(res)
    if d.get("is_paused") and d.get("resume_token"):
        try:
            async with httpx.AsyncClient(timeout=10.0) as c:
                r = await c.post(f"{_PILOT_URL}/inbox/refile", json=d)
            if r.status_code >= 400:
                raise RuntimeError(f"the inbox answered HTTP {r.status_code}")
        except Exception as e:
            # Same reasoning: a gate nobody can see is a run that waits for ever.
            _log.warning("could not re-file the next gate into the inbox: %s", e)
            pipeline_runlog.log_event(
                req.run_id or d.get("run_id"), "run_result", ok=False,
                status="paused_unfiled",
                error=f"paused at a further gate, but the inbox did not take it: {e}",
            )


@app.post("/pipeline/resume")
async def pipeline_resume(req: PipelineResumeRequest):
    """Resume a paused workflow with the external decision (Pilot inbox click).

    ``background=True`` detaches the resume: the remaining tail (which can be long —
    several video steps after a gate) runs without blocking the HTTP call, so the
    inbox click returns at once and the run continues server-side (visible in the
    run log). A further gate is re-filed into the inbox via the Pilot callback.
    """
    if req.background:
        task = asyncio.create_task(_bg_resume_and_refile(req))
        _bg_resume_tasks.add(task)
        task.add_done_callback(_bg_resume_tasks.discard)
        return {"ok": True, "status": "resuming", "is_paused": False}
    try:
        res = await resume_pipeline(
            req.token,
            response=req.response,
            approve=req.approve,
            cancel=req.cancel,
            runner=req.runner,
            run_id=req.run_id,
        )
    except PipelineError as e:
        raise HTTPException(status_code=502, detail=f"pipeline runner error: {e}")
    return _pipeline_result_to_dict(res)
