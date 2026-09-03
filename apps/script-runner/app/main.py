#!/usr/bin/env python3
"""
Mora02 Script Runner API
FastAPI service for gifer, clipper, typer scripts
"""

import asyncio
import json
import os
import re
import time
import uuid
import shutil
import subprocess
import httpx
from pathlib import Path
from datetime import datetime, timezone
from contextlib import nullcontext
from typing import Optional, List
from fastapi import FastAPI, UploadFile, File, HTTPException, Form, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from mora02_core import auth
from mora02_core import assets as asset_refs
from mora02_core import pricing
from mora02_core.llm import models as llm_models
from mora02_core._common import get_logger
from mora02_core.db import api as db_api
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
from mora02_core.llm import complete_qwen, complete_qwen_usage, complete_claude_usage
from mora02_core.media import tts as tts_lib
from mora02_core.media import MediaError, create_clip, create_gif, create_text_frame, extract_frame, mux_audio
from mora02_core.notify import notify, NotifyError
from mora02_core.pipeline import run_pipeline, run_pipeline_spec, rerun_pipeline_spec, resume_pipeline, PipelineError, spec as pipeline_spec, vocab as pipeline_vocab, runlog as pipeline_runlog, runbucket as pipeline_runbucket
from mora02_core.publish import post_to_linkedin, LinkedInError
from mora02_core import web

# The agent layer keeps its endpoints in their own module (see agents.py).
from agents import router as agents_router
# ...and its MCP surface in another: /mcp is a protocol, not an endpoint, and
# the tools it exposes are deliberately fewer than the routes below.
from mcp_tools import router as mcp_router

# ============================================================================
# CONFIG
# ============================================================================

_log = get_logger("script-runner")

DATA_DIR = Path("/data")
WIP_DIR = DATA_DIR / "wip"
FINAL_DIR = DATA_DIR / "final"

# Path mapping (container → host)
CONTAINER_DATA_PATH = "/data"
HOST_DATA_PATH = "/opt/mora02/output/_default/script-bot"

# Publish destinations (container paths)
PUBLISH_DESTINATIONS = {
    "socialmedia": Path("/socialmedia-assets"),  # Mounted volume
}

# nginx-images URL for assets
NGINX_BASE_URL = "http://mora02.local:8092/script-bot-assets"

# Stock photo APIs — keys via central env loader (mora02_core.auth)
PEXELS_API_KEY = auth.get("PEXELS_API_KEY", "")
PIXABAY_API_KEY = auth.get("PIXABAY_API_KEY", "")

# Ensure directories exist
for d in [WIP_DIR, FINAL_DIR, FINAL_DIR / "gifer", FINAL_DIR / "clipper", FINAL_DIR / "typer", FINAL_DIR / "pexels", FINAL_DIR / "pixabay"]:
    d.mkdir(parents=True, exist_ok=True)

# ============================================================================
# APP SETUP
# ============================================================================

app = FastAPI(
    title="Mora02 Script Runner",
    description="API for gifer, clipper, typer scripts",
    version="1.2.0"
)

app.include_router(agents_router)
app.include_router(mcp_router)

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

class FinalizeRequest(BaseModel):
    session_id: str
    filename: str
    script_type: str  # gifer, clipper, typer

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

class PublishAssetRequest(BaseModel):
    source_type: str  # gifer, clipper, typer
    source_folder: str  # e.g. "2601241945_abc123"
    source_file: str  # e.g. "2601241945_abc123.mp4"
    target_channel: str  # socialmedia, landingpage, etc.

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
# HELPERS
# ============================================================================

def create_session() -> str:
    """Create new session with unique ID"""
    session_id = datetime.now().strftime("%y%m%d%H%M") + "_" + uuid.uuid4().hex[:6]
    session_dir = WIP_DIR / session_id
    (session_dir / "input").mkdir(parents=True, exist_ok=True)
    (session_dir / "output").mkdir(parents=True, exist_ok=True)
    return session_id

def get_session_dir(session_id: str) -> Path:
    """Get session directory, raise if not exists"""
    session_dir = WIP_DIR / session_id
    if not session_dir.exists():
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return session_dir

def create_timestamp() -> str:
    """Create timestamp for filenames — format: YYMMDD-HHMM"""
    return datetime.now().strftime("%y%m%d-%H%M")

def container_to_host_path(container_path: str) -> str:
    """Convert container path to host path"""
    return container_path.replace(CONTAINER_DATA_PATH, HOST_DATA_PATH)

def get_nginx_url(script_type: str, folder: str, filename: str) -> str:
    """Get nginx URL for asset"""
    return f"{NGINX_BASE_URL}/{script_type}/{folder}/{filename}"

async def create_baserow_entry(script_type: str, folder: str, files: List[str], host_path: str):
    """Create entry in Baserow sb_assets table via mora02_core.db.api."""
    try:
        first_file = files[0] if files else ""
        data = {
            "type": script_type,
            "path": host_path,
            "filename": ", ".join(files),
            "files_count": len(files),
            "preview_url": get_nginx_url(script_type, folder, first_file),
            "created": datetime.now().isoformat(),
        }
        return await db_api.insert("sb_assets", data)
    except Exception as e:
        _log.warning("baserow insert failed: %s", e)
        return None

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
    shutil.rmtree(session_dir)
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
            create_gif(
                input_files=image_files,
                output_path=output_file,
                durations=request.durations,
                quality=request.quality,
                size=request.size,
            )
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
            create_text_frame(
                text=request.text,
                output_path=output_file,
                size=request.size,
                template=request.template,
                font=request.font,
                fontsize=request.fontsize,
                layout=request.layout,
            )
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
            create_clip(
                input_files=media_files,
                output_path=output_file,
                resolution=request.resolution,
                durations=request.durations,
                animation=request.animation,
                direction=request.direction,
                intensity=request.intensity,
                transition=request.transition,
            )
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
    media_types = {
        '.gif': 'image/gif',
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.mp4': 'video/mp4',
        '.webm': 'video/webm'
    }
    media_type = media_types.get(suffix, 'application/octet-stream')
    
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
    
    # Create final directory
    final_path = FINAL_DIR / request.script_type / folder_name
    final_path.mkdir(parents=True, exist_ok=True)
    
    # Copy output files
    copied_files = []
    for f in output_files:
        if f.is_file():
            shutil.copy2(f, final_path / f.name)
            copied_files.append(f.name)
    
    # Copy sourcefiles for gifer and clipper
    sourcefiles = []
    if request.script_type in ["gifer", "clipper"]:
        if input_dir.exists():
            sourcefiles_path = final_path / "sourcefiles"
            sourcefiles_path.mkdir(exist_ok=True)
            for f in sorted(input_dir.glob("*")):
                if f.is_file():
                    shutil.copy2(f, sourcefiles_path / f.name)
                    sourcefiles.append(f.name)
    
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
    shutil.rmtree(session_dir)
    
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

@app.post("/publish-asset")
async def publish_asset(request: PublishAssetRequest):
    """
    Publish an asset to a specific channel (e.g., socialmedia).
    Copies file from script-bot/final to target location.
    Returns filename for use in SM_content.media_path
    """
    # Validate target channel
    if request.target_channel not in PUBLISH_DESTINATIONS:
        return {
            "success": False, 
            "error": f"Unknown channel: {request.target_channel}. Available: {list(PUBLISH_DESTINATIONS.keys())}"
        }
    
    # Build source path
    source_path = FINAL_DIR / request.source_type / request.source_folder / request.source_file
    
    if not source_path.exists():
        return {"success": False, "error": f"Source file not found: {source_path}"}
    
    # Get destination directory
    dest_dir = PUBLISH_DESTINATIONS[request.target_channel]
    dest_dir.mkdir(parents=True, exist_ok=True)
    
    # Copy file to destination
    dest_file = dest_dir / request.source_file
    shutil.copy2(source_path, dest_file)
    
    # Return the filename (this is what goes into SM_content.media_path)
    return {
        "success": True,
        "channel": request.target_channel,
        "filename": request.source_file,
        "media_path": request.source_file,  # Ready for SM_content.media_path
        "source": str(source_path),
        "destination": str(dest_file)
    }

# Legacy finalize endpoint (single file) - kept for backwards compatibility
@app.post("/finalize")
async def finalize_file(request: FinalizeRequest):
    """Move file to final directory and return permanent URL (legacy)"""
    session_dir = get_session_dir(request.session_id)
    source_file = session_dir / "output" / request.filename
    
    if not source_file.exists():
        raise HTTPException(status_code=404, detail="File not found")
    
    final_subdir = FINAL_DIR / request.script_type
    final_subdir.mkdir(parents=True, exist_ok=True)
    
    dest_file = final_subdir / request.filename
    shutil.copy2(source_file, dest_file)
    
    final_url = f"/final/{request.script_type}/{request.filename}"
    host_path = container_to_host_path(str(dest_file))
    
    return {
        "success": True,
        "filename": request.filename,
        "path": host_path,
        "url": final_url,
        "script_type": request.script_type
    }

@app.get("/final/{script_type}/{filename}")
async def get_final_file(script_type: str, filename: str):
    """Serve finalized file (legacy single-file endpoint)"""
    filepath = FINAL_DIR / script_type / filename
    
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="File not found")
    
    suffix = filepath.suffix.lower()
    media_types = {
        '.gif': 'image/gif',
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.mp4': 'video/mp4'
    }
    media_type = media_types.get(suffix, 'application/octet-stream')
    
    return FileResponse(filepath, media_type=media_type)

@app.get("/final/{script_type}/{folder}/{filename}")
async def get_final_folder_file(script_type: str, folder: str, filename: str):
    """Serve file from finalized folder"""
    filepath = FINAL_DIR / script_type / folder / filename
    
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="File not found")
    
    suffix = filepath.suffix.lower()
    media_types = {
        '.gif': 'image/gif',
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.mp4': 'video/mp4',
        '.webm': 'video/webm',
        '.mov': 'video/quicktime'
    }
    media_type = media_types.get(suffix, 'application/octet-stream')
    
    return FileResponse(filepath, media_type=media_type)

@app.get("/final/{script_type}/{folder}/sourcefiles/{filename}")
async def get_sourcefile(script_type: str, folder: str, filename: str):
    """Serve sourcefile from finalized folder"""
    filepath = FINAL_DIR / script_type / folder / "sourcefiles" / filename
    
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="File not found")
    
    suffix = filepath.suffix.lower()
    media_types = {
        '.gif': 'image/gif',
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.webp': 'image/webp',
        '.mp4': 'video/mp4',
        '.mov': 'video/quicktime',
        '.webm': 'video/webm'
    }
    media_type = media_types.get(suffix, 'application/octet-stream')
    
    return FileResponse(filepath, media_type=media_type)

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
        folder_name = f"img_{timestamp}_{request.source}_{request.image_id}"
        filename = f"img_{timestamp}_{request.source}_{request.image_id}{ext}"
        
        # Save to final directory
        final_path = FINAL_DIR / request.source / folder_name
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
        "version": "1.4.0"
    }

@app.get("/")
async def root():
    """API info"""
    return {
        "service": "Mora02 Script Runner",
        "version": "1.4.0",
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

import re as _re

DOWNLOADS_DIR = DATA_DIR / "downloads"
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
NGINX_DOWNLOADS_URL = "http://mora02.local:8092/script-bot-downloads"

class SaveFileRequest(BaseModel):
    filename: str
    content: str
    add_timestamp: bool = True

@app.post("/save-file")
async def save_file(request: SaveFileRequest):
    filename = _re.sub(r'[^\w\-_.]', '_', request.filename)
    if request.add_timestamp and not _re.match(r'^\d{6}-\d{4}_', filename):
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


def _pipeline_result_to_dict(res) -> dict:
    """Flatten a PipelineResult for the JSON response (Pilot reads this verbatim)."""
    return {
        "ok": res.ok,
        "status": res.status,
        "is_paused": res.is_paused,
        "resume_token": res.resume_token,
        "output": res.output,
        "requires_input": res.requires_input,
        "requires_approval": res.requires_approval,
        "error": res.error,
        "runner": res.runner,
        # Pilot files this into the inbox item and hands it back on resume, so a
        # human decision can be logged against the run it belongs to.
        "run_id": getattr(res, "run_id", None),
    }


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
_PIPELINE_SPECS_DIR = os.environ.get("MORA02_PIPELINE_SPECS_DIR", "/data/pipelines/specs")


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
        base = Path(_PIPELINE_SPECS_DIR) / req.name
        cands = [base] if base.suffix else [
            base.with_suffix(ext) for ext in (".json", ".yaml", ".yml")
        ]
        match = next((str(p) for p in cands if p.is_file()), None)
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
        start = next(
            (e for e in pipeline_runlog.read_events(req.source_run_id)
             if e.get("kind") == "run_start"),
            None,
        )
        if start is None:
            raise HTTPException(
                status_code=404, detail=f"no run log for {req.source_run_id!r}")
        spec = start.get("spec")
        if spec is None:
            # Runs recorded before the spec was logged: nothing to plan against.
            raise HTTPException(
                status_code=409,
                detail=f"run {req.source_run_id!r} predates spec recording — "
                       "pass 'spec' explicitly to re-run it",
            )
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
        start = next(
            (e for e in pipeline_runlog.read_events(req.source_run_id)
             if e.get("kind") == "run_start"),
            None,
        )
        spec = (start or {}).get("spec")
        if spec is None:
            raise HTTPException(
                status_code=409,
                detail=f"run {req.source_run_id!r} has no recorded spec — pass 'spec'")
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
    flows = []
    specs = Path(_PIPELINE_SPECS_DIR)
    if specs.is_dir():
        for p in sorted(specs.glob("*.json")):
            try:
                spec = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            flows.append({
                "name": spec.get("name") or p.stem,
                "file": p.stem,
                "description": spec.get("description", ""),
                "tags": spec.get("tags", []),
                "updated": spec.get("updated", ""),
                "steps": len(spec.get("steps", [])),
            })
    return {"flows": flows}


@app.get("/pipeline/flow/{name}")
async def pipeline_flow(name: str):
    """Return one named flow spec (matched by spec name or filename stem)."""
    specs = Path(_PIPELINE_SPECS_DIR)
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
_FLOW_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")


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

    specs = Path(_PIPELINE_SPECS_DIR)
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
    target = Path(_PIPELINE_SPECS_DIR) / f"{name}.json"
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
    try:
        files = sorted(Path(d).glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:40]
    except OSError:
        files = []
    for p in files:
        events = _read_run_events(p.stem) or []
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
    events = _read_run_events(os.path.basename(run_id))
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
    except Exception:
        _log.exception("background resume failed")
        return
    d = _pipeline_result_to_dict(res)
    if d.get("is_paused") and d.get("resume_token"):
        try:
            async with httpx.AsyncClient(timeout=10.0) as c:
                await c.post(f"{_PILOT_URL}/inbox/refile", json=d)
        except Exception:
            _log.warning("could not re-file the next gate into the inbox")


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


# ============================================================================
# ENDPOINTS - PIPELINE STEP VOCABULARY (Nordstern)
# ============================================================================
# The step *verbs* a pipeline is built from (run/resume above are the HITL
# *orchestration*). A Lobster `run:` step shells `curl` here; the heavy work
# (mora02_core: media/comfyui/llm) runs in this container — the executor
# (ADR-020).
#
# Contract (derived from the vertical slices, kept deliberately small):
#   - Inputs arrive newline-separated on the REQUEST BODY, because Lobster only
#     passes a prior step's output via `stdin: $step.stdout` — it does NOT
#     interpolate `$step.*` inside a `run:` string. So the previous step's stdout
#     becomes this step's stdin. An input line is an asset ref (media step) or a
#     plain text value (a value produced by an LLM step) — same transport.
#   - Step parameters arrive as QUERY params (resolution, pick, subject, …).
#   - Every result carries `out`: the single stdout string this step emits — an
#     asset ref for media steps, a text value for value steps. `?fmt=ref|out`
#     returns `out` bare as text/plain so it chains cleanly as the next step's
#     `$step.stdout`; otherwise a JSON envelope {ok, op, out, type, …} for
#     debugging / direct callers.
#
# Each handler is async: value/comfyui steps await httpx; the blocking ffmpeg
# clipper is pushed to a thread inside its handler so it can't stall the loop.

_STEP_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")

# llm.image_prompt — turns a short subject into one rich text-to-image prompt.
# Plain local qwen completion (NOT the openclaw llm-task plugin, which breaks on
# llama.cpp's constrained tool-calling — Phase-0 finding; NOT cloud — the
# control-plane guardrail keeps orchestration local).
_IMAGE_PROMPT_SYSTEM = (
    "You are an expert text-to-image prompt engineer. Expand the user's subject "
    "into ONE vivid, concrete image prompt covering subject, setting, lighting, "
    "mood, composition and style. Output ONLY the prompt text — a single line, "
    "no preamble, no quotes, no markdown."
)


async def _step_source_file(inputs: List[str], params: dict) -> dict:
    """source.file — bring a file from a store into the pipeline as a ref.

    Params: store (default "comfyui"), name (exact filename) or pick
    ("latest"|"oldest", default "latest" over the store's image files).
    """
    store = params.get("store", "comfyui")
    root = asset_refs.store_root(store)
    name = params.get("name")
    if name:
        target = root / name
        if not target.is_file():
            raise ValueError(f"{name!r} not found in store {store!r}")
    else:
        candidates = sorted(
            (p for p in root.glob("**/*")
             if p.is_file() and p.suffix.lower() in _STEP_IMAGE_EXTS),
            key=lambda p: p.stat().st_mtime,
        )
        if not candidates:
            raise ValueError(f"no image files in store {store!r} ({root})")
        target = candidates[-1] if params.get("pick", "latest") != "oldest" else candidates[0]
    ref = asset_refs.ref_for_path(target, store)
    return {"ok": True, "op": "source.file", "out": ref, "type": "image"}


async def _step_source_find(inputs: List[str], params: dict) -> dict:
    """source.find — pick a named file out of a store, by path or pattern.

    The counterpart to source.file, which picks by modification date: that
    answers "the newest thing ComfyUI made" and cannot answer "the product
    photo for SKU 4711". This one names what it wants.

    Params: store (default "library"), and exactly one of path (an exact path
    inside the store) or match (a glob). pick decides what happens when a glob
    matches several files:

      one    (default) refuse, and list the candidates
      first  alphabetically first by path
      last   alphabetically last
      all    every match, one ref per line

    Sorting is by path, never by mtime — a lookup that silently changes its
    answer when a file is touched is the thing this op exists to replace.
    """
    store = params.get("store", "library")
    root = asset_refs.store_root(store)
    if not root.is_dir():
        raise ValueError(f"store {store!r} is not mounted here ({root})")

    path, match = params.get("path"), params.get("match")
    if bool(path) == bool(match):
        raise ValueError("source.find needs exactly one of ?path= or ?match=")

    # A pattern that walks upwards is refused by name rather than by outcome.
    # pathlib.glob simply finds nothing for "../../x", so without this the
    # caller would be told "nothing matches" — true, but it reads as "the
    # pattern was fine and the store is empty of it", which is a different
    # sentence from "you may not look there".
    if match and (".." in Path(match).parts or match.startswith("/")):
        raise ValueError(
            f"{match!r} points outside store {store!r} — a pattern stays inside "
            f"its store root"
        )

    # Containment is checked here rather than left to ref_for_path, which
    # falls back to the bare filename for a path outside the root instead of
    # refusing — safe, but silent, and silence is what we are avoiding.
    def _inside(candidate: Path) -> Path:
        resolved = candidate.resolve()
        try:
            resolved.relative_to(root.resolve())
        except ValueError:
            raise ValueError(
                f"{str(candidate)!r} leaves store {store!r} — a lookup may not "
                f"reach outside its store root"
            )
        return resolved

    if path:
        target = _inside(root / path)
        if not target.is_file():
            raise ValueError(f"{path!r} not found in store {store!r} ({root})")
        found = [target]
    else:
        # Out-of-scope hits are dropped, not refused: a pattern that happens
        # to span two customers must not answer customer A with customer B's
        # file name in an error message (T3 of the material plan -- not
        # visible, rather than refused). An exact path is a different case and
        # is still refused above, because the caller named it themselves.
        found = sorted(
            hit for hit in (_inside(p) for p in root.glob(match) if p.is_file())
            if asset_refs.in_scope(store, str(hit.relative_to(root.resolve())))
        )

    if not found:
        # Say what was looked for and where, and how much is there at all: an
        # empty result with no context sends the reader hunting for a typo in
        # the wrong half of the problem.
        # Counted within the scope in force. The file names are already hidden
        # from a foreign project; a total that includes them would still say
        # "there is more here than you can see", which is the same leak one
        # size smaller.
        total = sum(
            1 for f in root.rglob("*")
            if f.is_file()
            and asset_refs.in_scope(store, str(f.relative_to(root.resolve())))
        )
        raise ValueError(
            f"nothing matches {match!r} in store {store!r} ({root}); "
            f"the store holds {total} files"
        )

    pick = params.get("pick", "one")
    if pick == "one" and len(found) > 1:
        shown = ", ".join(str(p.relative_to(root)) for p in found[:8])
        more = f" (+{len(found) - 8} more)" if len(found) > 8 else ""
        raise ValueError(
            f"{match!r} matches {len(found)} files in store {store!r}: {shown}{more}. "
            f"Narrow the pattern, or say pick=first|last|all."
        )

    chosen = found if pick == "all" else [found[-1] if pick == "last" else found[0]]
    refs = [asset_refs.ref_for_path(p, store) for p in chosen]
    kind = _step_kind_for_suffix(chosen[0].suffix) if len(chosen) == 1 else "any"
    return {
        "ok": True, "op": "source.find", "out": "\n".join(refs), "type": kind,
        "log": {"store": store, "matched": len(found), "picked": len(chosen)},
    }


def _step_kind_for_suffix(suffix: str) -> str:
    """Name the wire type of a file, so the next step knows what it got."""
    s = suffix.lower()
    if s in _STEP_IMAGE_EXTS:
        return "image"
    if s in {".mp4", ".mov", ".webm", ".gif", ".mkv"}:
        return "video"
    if s in {".mp3", ".wav", ".flac", ".m4a", ".ogg"}:
        return "audio"
    return "any"


async def _step_llm_image_prompt(inputs: List[str], params: dict) -> dict:
    """llm.image_prompt — subject -> one rich image-prompt TEXT value (local qwen).

    Subject from `?subject=` or, failing that, from stdin (a value piped from a
    prior step). The produced value flows on stdout exactly like a ref does.
    """
    subject = params.get("subject") or "\n".join(inputs).strip()
    if not subject:
        raise ValueError("llm.image_prompt needs a subject (?subject= or on stdin)")
    prompt = (await complete_qwen(
        [{"role": "user", "content": subject}],
        _IMAGE_PROMPT_SYSTEM,
    )).strip()
    if not prompt:
        raise ValueError("llm.image_prompt got an empty completion from qwen")
    return {"ok": True, "op": "llm.image_prompt", "out": prompt, "type": "text"}


def _flag_truncation(usage: dict, op: str) -> None:
    """Mark a completion the model did NOT finish on its own.

    The server reports finish_reason="length" when it stopped counting rather
    than stopping at the end of the answer — the text then breaks off
    mid-sentence and nothing else says so. Only happens when a ceiling was set
    explicitly or the context filled up; either way the reader must be told.
    """
    if usage.get("finish_reason") == "length":
        usage["truncated"] = True
        usage["hint"] = (
            f"Output cut off after {usage.get('tokens_out')} tokens — "
            f"raise max_tokens or drop it entirely."
        )
        _log.warning("%s: output truncated (finish_reason=length)", op)


# Text-LLM ops (Welle 2). All local qwen via complete_qwen_usage; each returns
# the produced text as the stdout value (so it chains like any other value) plus
# a "log" dict with token usage for the run log. Control-plane stays local — none
# of these touch the cloud (ADR-022 / control-plane-local guardrail).
async def _step_llm_complete(inputs: List[str], params: dict) -> dict:
    """llm.complete — free-form completion. Prompt from ?prompt= or stdin."""
    prompt = params.get("prompt") or "\n".join(inputs).strip()
    if not prompt:
        raise ValueError("llm.complete needs a prompt (?prompt= or on stdin)")
    system = params.get("system", "You are a helpful assistant.")
    temperature = float(params["temperature"]) if params.get("temperature") else 0.7
    # No default ceiling: "500 words" must produce 500 words, not 512 tokens.
    max_tokens = int(params["max_tokens"]) if params.get("max_tokens") else None
    text, usage = await complete_qwen_usage(
        [{"role": "user", "content": prompt}], system,
        temperature=temperature, max_tokens=max_tokens,
    )
    if not text:
        raise ValueError("llm.complete got an empty completion from qwen")
    _flag_truncation(usage, "llm.complete")
    return {"ok": True, "op": "llm.complete", "out": text, "type": "text", "log": usage}


async def _step_llm_summarize(inputs: List[str], params: dict) -> dict:
    """llm.summarize — condense the stdin text. Param: max_tokens (length budget)."""
    text_in = "\n".join(inputs).strip()
    if not text_in:
        raise ValueError("llm.summarize needs text on stdin")
    max_tokens = int(params["max_tokens"]) if params.get("max_tokens") else None
    system = ("Summarize the user's text concisely and faithfully. "
              "Output only the summary — no preamble, no commentary.")
    text, usage = await complete_qwen_usage(
        [{"role": "user", "content": text_in}], system, max_tokens=max_tokens,
    )
    if not text:
        raise ValueError("llm.summarize got an empty completion from qwen")
    _flag_truncation(usage, "llm.summarize")
    return {"ok": True, "op": "llm.summarize", "out": text, "type": "text", "log": usage}


async def _step_llm_classify(inputs: List[str], params: dict) -> dict:
    """llm.classify — pick exactly one label for the stdin text. Param: labels."""
    text_in = "\n".join(inputs).strip()
    if not text_in:
        raise ValueError("llm.classify needs text on stdin")
    labels = params.get("labels")
    if not labels:
        raise ValueError("llm.classify needs ?labels= (comma-separated)")
    label_list = [l.strip() for l in labels.split(",") if l.strip()]
    if not label_list:
        raise ValueError("llm.classify got no usable labels")
    system = ("Classify the user's text into exactly one of these labels: "
              f"{', '.join(label_list)}. Output ONLY the chosen label, nothing else.")
    text, usage = await complete_qwen_usage(
        [{"role": "user", "content": text_in}], system, max_tokens=32,
    )
    # Snap to a declared label if the model wrapped it in extra words.
    chosen = text.strip()
    low = chosen.lower()
    snapped = next((l for l in label_list if l.lower() == low), None) \
        or next((l for l in label_list if l.lower() in low), None)
    if not chosen:
        raise ValueError("llm.classify got an empty completion from qwen")
    if snapped is None:
        # The op promises exactly one of the labels, and a later step branches on
        # the answer. Passing an unrecognised value on would decide a branch by
        # accident and say nothing; llm.complete is the op for free-form text.
        raise ValueError(
            f"llm.classify: the model answered {chosen[:80]!r}, which is none of "
            f"the labels ({', '.join(label_list)})"
        )
    out = snapped
    _flag_truncation(usage, "llm.classify")
    return {"ok": True, "op": "llm.classify", "out": out, "type": "text", "log": usage}


async def _step_llm_extract(inputs: List[str], params: dict) -> dict:
    """llm.extract — pull fields from the stdin text as JSON. Param: fields."""
    text_in = "\n".join(inputs).strip()
    if not text_in:
        raise ValueError("llm.extract needs text on stdin")
    fields = params.get("fields")
    if not fields:
        raise ValueError("llm.extract needs ?fields= (comma-separated)")
    field_list = [f.strip() for f in fields.split(",") if f.strip()]
    if not field_list:
        raise ValueError("llm.extract got no usable fields")
    system = ("Extract information from the user's text and return ONLY a JSON object "
              f"with exactly these keys: {', '.join(field_list)}. Use null for any "
              "field not present. No markdown fences, no commentary.")
    text, usage = await complete_qwen_usage(
        [{"role": "user", "content": text_in}], system,
    )
    if not text:
        raise ValueError("llm.extract got an empty completion from qwen")
    _flag_truncation(usage, "llm.extract")
    return {"ok": True, "op": "llm.extract", "out": text, "type": "text", "log": usage}


async def _step_llm_translate(inputs: List[str], params: dict) -> dict:
    """llm.translate — translate the stdin text. Params: to (required), from."""
    text_in = "\n".join(inputs).strip()
    if not text_in:
        raise ValueError("llm.translate needs text on stdin")
    to = params.get("to")
    if not to:
        raise ValueError("llm.translate needs ?to= (target language)")
    src = params.get("from")
    frm = f" from {src}" if src else ""
    system = (f"Translate the user's text{frm} into {to}. "
              "Output only the translation — no preamble, no quotes, no commentary.")
    text, usage = await complete_qwen_usage(
        [{"role": "user", "content": text_in}], system,
    )
    if not text:
        raise ValueError("llm.translate got an empty completion from qwen")
    _flag_truncation(usage, "llm.translate")
    return {"ok": True, "op": "llm.translate", "out": text, "type": "text", "log": usage}


# Cloud LLM ops (Claude) — PERIPHERAL content tasks only. Control-plane
# orchestration stays local (qwen); these are opt-in per-step cloud calls.
# Each logs tokens AND cost_usd (from the MODELS pricing) via result["log"].
async def _step_cloud_complete(inputs: List[str], params: dict) -> dict:
    """cloud.complete — free-form completion via Claude. Prompt from ?prompt= or stdin."""
    prompt = params.get("prompt") or "\n".join(inputs).strip()
    if not prompt:
        raise ValueError("cloud.complete needs a prompt (?prompt= or on stdin)")
    text, usage = await complete_claude_usage(
        [{"role": "user", "content": prompt}],
        params.get("system", "You are a helpful assistant."),
        model_key=params.get("model", "sonnet"),
        # Unset unless the step asks for it: the current models no longer take a
        # sampling parameter, and sending 0.7 by default made every cloud step
        # fail outright.
        temperature=float(params["temperature"]) if params.get("temperature") else None,
        # 16000, not 1024: the Anthropic guidance for non-streaming requests, and
        # a ceiling rather than a spend - a shorter answer costs exactly what it
        # generates. The old 1024 (~750 words) cut prose mid-sentence, the same
        # trap the local path had at 512.
        max_tokens=int(params["max_tokens"]) if params.get("max_tokens") else 16000,
    )
    if not text:
        raise ValueError("cloud.complete got an empty completion from Claude")
    _flag_truncation(usage, "cloud.complete")
    return {"ok": True, "op": "cloud.complete", "out": text, "type": "text", "log": usage}


async def _step_cloud_vision(inputs: List[str], params: dict) -> dict:
    """cloud.vision — ask Claude about an image ref (stdin) -> text answer."""
    import base64
    import mimetypes
    if not inputs:
        raise ValueError("cloud.vision needs an image ref on stdin")
    path = asset_refs.resolve_ref(inputs[0])
    if not path.is_file():
        raise ValueError(f"image not found for ref {inputs[0]!r} ({path})")
    media_type = mimetypes.guess_type(str(path))[0] or "image/png"
    data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
    query = params.get("query") or "Describe this image in detail."
    text, usage = await complete_claude_usage(
        [{"role": "user", "content": query}],
        "You are a precise vision assistant.",
        model_key=params.get("model", "haiku"),
        image_data={"media_type": media_type, "data": data},
        max_tokens=int(params["max_tokens"]) if params.get("max_tokens") else 1024,
    )
    if not text:
        raise ValueError("cloud.vision got an empty answer from Claude")
    _flag_truncation(usage, "cloud.vision")
    return {"ok": True, "op": "cloud.vision", "out": text, "type": "text", "log": usage}


async def _step_image_generate(inputs: List[str], params: dict) -> dict:
    """image.generate — prompt TEXT -> a generated image ref (ComfyUI).

    Prompt from stdin (an llm step's value) or `?prompt=`. Params: flow
    (default "photo"), format, batch_size, testrun=1.
    """
    prompt = params.get("prompt") or "\n".join(inputs).strip()
    if not prompt:
        raise ValueError("image.generate needs a prompt (on stdin or ?prompt=)")
    result = await generate_images(
        prompt,
        flow=params.get("flow", "photo"),
        format=params.get("format"),
        batch_size=int(params["batch_size"]) if params.get("batch_size") else None,
        testrun=params.get("testrun") == "1",
    )
    assets = result.get("assets") or []
    if not assets:
        raise ValueError(result.get("error") or "image.generate produced no image")
    ref = asset_refs.ref_for_path(assets[0].path, "comfyui")
    return {"ok": True, "op": "image.generate", "out": ref, "type": "image",
            "prompt": prompt, "count": len(assets),
            "log": {"flow": result.get("flow"), "model": result.get("flow_name"),
                    "seed": result.get("seed"), "count": len(assets),
                    "cost_usd": result.get("cost_usd")}}


async def _step_image_edit(inputs: List[str], params: dict) -> dict:
    """image.edit — an image ref + an instruction -> an edited image ref (ComfyUI).

    The revision primitive: keep the picture, change one thing about it. Distinct
    from re-running image.generate with a richer prompt, which re-rolls the whole
    image — a related rabbit, not the same rabbit in a hat.
    """
    if not inputs:
        raise ValueError("image.edit needs an image ref on stdin")
    src = asset_refs.path_for_ref(inputs[0])
    if not src:
        raise ValueError(f"image.edit: no nginx path for ref {inputs[0]!r}")
    prompt = params.get("prompt")
    if not prompt:
        raise ValueError("image.edit needs a prompt (?prompt=) saying what to change")
    result = await edit_image(
        src,
        prompt,
        flow=params.get("flow", "nanban"),
        image_format=params.get("format"),
        temperature=float(params["temperature"]) if params.get("temperature") else None,
    )
    assets = result.get("assets") or []
    if not assets:
        raise ValueError(result.get("error") or "image.edit produced no image")
    ref = asset_refs.ref_for_path(assets[0].path, "comfyui")
    return {"ok": True, "op": "image.edit", "out": ref, "type": "image",
            "prompt": prompt, "source": inputs[0],
            "log": {"flow": result.get("flow"), "model": result.get("flow_name"),
                    "source_ref": inputs[0], "cost_usd": result.get("cost_usd")}}


async def _step_image_cutout(inputs: List[str], params: dict) -> dict:
    """image.cutout — an image ref -> the subject on a transparent background.

    The mechanical counterpart to image.edit: no model reinterprets the picture,
    a matting model decides per pixel how much of it belongs to the subject. The
    result is a layer, not a new image — usable as an overlay, in a composite, or
    as the foreground plane of a parallax animation.
    """
    if not inputs:
        raise ValueError("image.cutout needs an image ref on stdin")
    src = asset_refs.path_for_ref(inputs[0])
    if not src:
        raise ValueError(f"image.cutout: no nginx path for ref {inputs[0]!r}")
    result = await cutout_image(
        src,
        model=params.get("model", "isnet"),
        device=params.get("device", "CUDA"),
    )
    assets = result.get("assets") or []
    if not assets:
        raise ValueError(result.get("error") or "image.cutout produced no image")
    ref = asset_refs.ref_for_path(assets[0].path, "comfyui")
    return {"ok": True, "op": "image.cutout", "out": ref, "type": "image",
            "source": inputs[0],
            "log": {"flow": result.get("flow"), "model": result.get("model"),
                    "source_ref": inputs[0]}}


async def _step_image_erase(inputs: List[str], params: dict) -> dict:
    """image.erase — an image ref -> the same scene with the subject painted out.

    The counterpart to image.cutout. Run both on one picture and it falls apart
    into two layers: the subject with alpha, and a complete background — the pair
    a parallax animation is built from.
    """
    if not inputs:
        raise ValueError("image.erase needs an image ref on stdin")
    src = asset_refs.path_for_ref(inputs[0])
    if not src:
        raise ValueError(f"image.erase: no nginx path for ref {inputs[0]!r}")
    result = await erase_image(
        src,
        prompt=params.get("prompt", ""),
        model=params.get("model", "isnet"),
        grow=int(params.get("grow", 90)),
        seed=int(params["seed"]) if params.get("seed") else None,
        steps=int(params["steps"]) if params.get("steps") else None,
    )
    assets = result.get("assets") or []
    if not assets:
        raise ValueError(result.get("error") or "image.erase produced no image")
    ref = asset_refs.ref_for_path(assets[0].path, "comfyui")
    return {"ok": True, "op": "image.erase", "out": ref, "type": "image",
            "source": inputs[0],
            "log": {"flow": result.get("flow"), "seed": result.get("seed"),
                    "grow": result.get("grow"), "source_ref": inputs[0]}}


async def _step_image_facefix(inputs: List[str], params: dict) -> dict:
    """image.facefix — an image ref -> the same image with the faces refined."""
    if not inputs:
        raise ValueError("image.facefix needs an image ref on stdin")
    src = asset_refs.path_for_ref(inputs[0])
    if not src:
        raise ValueError(f"image.facefix: no nginx path for ref {inputs[0]!r}")
    result = await facefix_image(
        src,
        prompt=params.get("prompt", ""),
        denoise=float(params["denoise"]) if params.get("denoise") else None,
        seed=int(params["seed"]) if params.get("seed") else None,
        steps=int(params["steps"]) if params.get("steps") else None,
    )
    assets = result.get("assets") or []
    if not assets:
        raise ValueError(result.get("error") or "image.facefix produced no image")
    ref = asset_refs.ref_for_path(assets[0].path, "comfyui")
    return {"ok": True, "op": "image.facefix", "out": ref, "type": "image",
            "source": inputs[0],
            "log": {"flow": result.get("flow"), "seed": result.get("seed"),
                    "source_ref": inputs[0]}}


# Visual-extend ops (Welle 4) — ComfyUI-backed. An input image ref is fed back
# into ComfyUI as a host-less nginx path (path_for_ref), which the uploader
# fetches from the internal nginx-images service. Outputs land in the comfyui
# store (ref_for_path falls back to the bare filename, like image.generate).
# Each logs its seed (+ flow for video) via the generic result["log"] channel.
async def _step_image_upscale(inputs: List[str], params: dict) -> dict:
    """image.upscale — enlarge an image ref (SDXL-Tile + UltraSharp) -> image ref."""
    if not inputs:
        raise ValueError("image.upscale needs an image ref on stdin")
    src = asset_refs.path_for_ref(inputs[0])
    if not src:
        raise ValueError(f"image.upscale: no nginx path for ref {inputs[0]!r}")
    result = await upscale_image(
        src,
        factor=float(params.get("factor", 2)),
        prompt=params.get("prompt", ""),
        denoise=float(params["denoise"]) if params.get("denoise") else None,
        seed=int(params["seed"]) if params.get("seed") else None,
    )
    assets = result.get("assets") or []
    if not assets:
        raise ValueError(result.get("error") or "image.upscale produced no image")
    out_ref = asset_refs.ref_for_path(assets[0].path, "comfyui")
    return {"ok": True, "op": "image.upscale", "out": out_ref, "type": "image",
            "url": asset_refs.url_for_ref(out_ref), "log": {"seed": result.get("seed")}}


async def _step_image_expand(inputs: List[str], params: dict) -> dict:
    """image.expand — outpaint an image ref to a larger canvas (FLUX) -> image ref."""
    if not inputs:
        raise ValueError("image.expand needs an image ref on stdin")
    src = asset_refs.path_for_ref(inputs[0])
    if not src:
        raise ValueError(f"image.expand: no nginx path for ref {inputs[0]!r}")
    result = await expand_image(
        src,
        prompt=params.get("prompt", ""),
        target_size=int(params.get("target_size", 1920)),
        feathering=int(params["feathering"]) if params.get("feathering") else None,
        seed=int(params["seed"]) if params.get("seed") else None,
    )
    assets = result.get("assets") or []
    if not assets:
        raise ValueError(result.get("error") or "image.expand produced no image")
    out_ref = asset_refs.ref_for_path(assets[0].path, "comfyui")
    return {"ok": True, "op": "image.expand", "out": out_ref, "type": "image",
            "url": asset_refs.url_for_ref(out_ref), "log": {"seed": result.get("seed")}}


async def _step_video_generate(inputs: List[str], params: dict) -> dict:
    """video.generate — WAN 2.2 text/image-to-video -> video ref.

    mode: t2v (prompt only), i2v (start image), i2i2v (start+end frames). For
    i2v/i2i2v the start image comes from ?start_image= or, failing that, stdin;
    end image from ?end_image=. Image refs are uploaded to ComfyUI first.
    """
    mode = params.get("mode", "t2v")
    flow = "wan-" + mode  # t2v -> wan-t2v, i2v -> wan-i2v, i2i2v -> wan-i2i2v
    start_ref = params.get("start_image")
    if mode in ("i2v", "i2i2v") and not start_ref and inputs:
        start_ref = inputs[0]
    end_ref = params.get("end_image")
    prompt = params.get("prompt") or (("\n".join(inputs).strip()) if mode == "t2v" else "")
    if mode == "t2v" and not prompt:
        raise ValueError("video.generate t2v needs a prompt (?prompt= or on stdin)")
    if mode in ("i2v", "i2i2v") and not start_ref:
        raise ValueError(f"video.generate {mode} needs a start_image (?start_image= or on stdin)")
    if mode == "i2i2v" and not end_ref:
        raise ValueError("video.generate i2i2v needs an end_image (?end_image=)")
    start_fn = await upload_image_url_to_comfyui(asset_refs.path_for_ref(start_ref)) if start_ref else None
    end_fn = await upload_image_url_to_comfyui(asset_refs.path_for_ref(end_ref)) if end_ref else None
    result = await generate_video(
        prompt or "",
        flow=flow,
        length=int(params["length"]) if params.get("length") else None,
        fps=int(params["fps"]) if params.get("fps") else None,
        seed=int(params["seed"]) if params.get("seed") else None,
        start_image=start_fn,
        end_image=end_fn,
    )
    assets = result.get("assets") or []
    if not assets:
        raise ValueError(result.get("error") or "video.generate produced no video")
    # ComfyUI writes videos into a "video/" subfolder; asset.id carries the
    # store-relative path *including* that subfolder, so build the ref from it.
    # (ref_for_path's basename fallback would drop the subfolder, leaving a ref
    # that resolves nowhere — videos differ from images, which have no subfolder.)
    out_ref = asset_refs.make_ref("comfyui", assets[0].id)
    return {"ok": True, "op": "video.generate", "out": out_ref, "type": "video",
            "url": asset_refs.url_for_ref(out_ref),
            "log": {"seed": result.get("seed"), "flow": result.get("flow")}}


async def _step_video_last_frame(inputs: List[str], params: dict) -> dict:
    """video.last_frame — extract a video's last (or first) frame as an image ref.

    Chains i2v videos: each new video starts from the prior video's final frame, so a
    continuous motion sequence grows one clip at a time. Input: one video ref on stdin.
    Param: position (last|first). The frame lands in the clipper store (writable and
    nginx-served, so it can feed video.generate's start_image). ffmpeg runs off the
    event loop.
    """
    if not inputs:
        raise ValueError("video.last_frame needs a video ref on stdin")
    in_ref = inputs[0]
    video_path = asset_refs.resolve_ref(in_ref)
    if not video_path.is_file():
        raise ValueError(f"video.last_frame: video not found for ref {in_ref!r}")
    position = params.get("position", "last")
    out_name = f"frame_{uuid.uuid4().hex[:8]}.png"
    out_path = asset_refs.store_root("clipper") / out_name
    await asyncio.to_thread(extract_frame, str(video_path), str(out_path), position)
    out_ref = asset_refs.make_ref("clipper", out_name)
    return {"ok": True, "op": "video.last_frame", "out": out_ref, "type": "image",
            "url": asset_refs.url_for_ref(out_ref)}


async def _step_music_generate(inputs: List[str], params: dict) -> dict:
    """music.generate — ACE-Step 1.5 tags(+optional lyrics)-to-music -> audio ref.

    Tags come from ?prompt= or stdin; lyrics from ?lyrics= (empty = instrumental).
    All ACE-Step controls are exposed as params (duration, bpm, key, time_signature,
    language, steps, seed, cfg_scale, temperature, top_p, top_k, min_p). An optional
    ref_audio (asset ref) is uploaded to ComfyUI first for reference-timbre transfer.
    Output lands in the "comfyui" store under the "music/" subfolder — the ref is
    built from asset.id (which includes that subfolder), like video.generate.
    """
    tags = params.get("prompt") or ("\n".join(inputs).strip() if inputs else "")
    lyrics = params.get("lyrics", "")
    if not tags and not lyrics:
        raise ValueError("music.generate needs tags (?prompt= or on stdin) or ?lyrics=")

    ref_audio = params.get("ref_audio")
    ref_fn = None
    if ref_audio:
        ref_fn = (await upload_image_url_to_comfyui(asset_refs.path_for_ref(ref_audio))
                  if ref_audio.startswith("asset://") else ref_audio)

    def _i(k):
        return int(params[k]) if params.get(k) else None

    def _f(k):
        return float(params[k]) if params.get(k) else None

    result = await generate_music(
        tags,
        lyrics=lyrics,
        duration=_i("duration"),
        bpm=_i("bpm"),
        steps=_i("steps"),
        seed=_i("seed"),
        top_k=_i("top_k"),
        key=params.get("key"),
        time_signature=params.get("time_signature"),
        language=params.get("language"),
        cfg_scale=_f("cfg_scale"),
        temperature=_f("temperature"),
        top_p=_f("top_p"),
        min_p=_f("min_p"),
        ref_audio=ref_fn,
    )
    assets = result.get("assets") or []
    if not assets:
        raise ValueError(result.get("error") or "music.generate produced no audio")
    out_ref = asset_refs.make_ref("comfyui", assets[0].id)
    return {"ok": True, "op": "music.generate", "out": out_ref, "type": "audio",
            "url": asset_refs.url_for_ref(out_ref),
            "log": {"seed": result.get("seed"), "flow": result.get("flow")}}


async def _step_notify_image(inputs: List[str], params: dict) -> dict:
    """notify.image — push an image ref to a chat (Signal) for human review, then
    pass the SAME ref through unchanged so the chain continues.

    Input: one image ref on stdin. Params: target (E.164; or env
    MORA02_SIGNAL_TARGET), channel (default "signal"), message (optional caption).
    The media file is sent by `openclaw message send --media` from *inside* the
    gateway container, so the resolved path must exist there too — mount the store
    identically in mora02-openclaw (same path this container resolves to).
    """
    if not inputs:
        raise ValueError("notify.image needs an image ref on stdin")
    ref = inputs[0]
    path = asset_refs.resolve_ref(ref)
    if not path.is_file():
        raise ValueError(f"image not found for ref {ref!r} ({path})")
    target = params.get("target") or os.environ.get("MORA02_SIGNAL_TARGET")
    if not target:
        raise ValueError("notify.image needs a target (?target= or MORA02_SIGNAL_TARGET)")
    try:
        await notify(
            params.get("channel", "signal"),
            target,
            params.get("message", ""),
            media=str(path),
        )
    except NotifyError as e:
        raise ValueError(f"signal send failed: {e}")
    return {"ok": True, "op": "notify.image", "out": ref, "type": "image"}


# Extension → wire type, for tagging a passed-through media ref in notify.
_NOTIFY_EXT_TYPE = {
    ".jpg": "image", ".jpeg": "image", ".png": "image", ".webp": "image",
    ".bmp": "image", ".gif": "image",
    ".mp4": "video", ".mov": "video", ".webm": "video", ".mkv": "video", ".avi": "video",
    ".wav": "audio", ".mp3": "audio", ".flac": "audio", ".ogg": "audio", ".m4a": "audio",
}


async def _step_notify(inputs: List[str], params: dict) -> dict:
    """notify — send the previous step's output (type-aware) to a chat, no pause;
    pass the input through unchanged so the chain continues.

    Generalizes notify.image: an ``asset://`` ref on stdin is resolved to a file
    and sent as ``media`` (image/video/audio — whatever it is); any other stdin
    value is sent as the message text. Params: target (E.164; or env
    MORA02_SIGNAL_TARGET), channel (default "signal"), message (caption / extra
    text), title, link. Like notify.image, a media file is sent by the gateway
    container, so its store must be mounted there at the same resolved path.
    """
    target = params.get("target") or os.environ.get("MORA02_SIGNAL_TARGET")
    if not target:
        raise ValueError("notify needs a target (?target= or MORA02_SIGNAL_TARGET)")

    # stdin reaches a step split into LINES (see the step endpoint). An asset ref
    # is a single line, so inputs[0] identifies it — but a text value must be
    # rejoined, or only its first paragraph would travel on.
    incoming = inputs[0] if inputs else ""
    media = None
    wire = "text"
    if incoming.startswith("asset://"):
        path = asset_refs.resolve_ref(incoming)
        if not path.is_file():
            raise ValueError(f"file not found for ref {incoming!r} ({path})")
        media = str(path)
        wire = _NOTIFY_EXT_TYPE.get(path.suffix.lower(), "any")
        message = params.get("message", "")
        passthrough = incoming
    else:
        # A text value (or nothing) on stdin: send as the message body, optionally
        # prefixed by ?message=.
        passthrough = "\n".join(inputs).strip()
        message = "\n".join(p for p in (params.get("message"), passthrough) if p)
        if not message:
            raise ValueError("notify needs media on stdin or a message")

    try:
        await notify(
            params.get("channel", "signal"),
            target,
            message,
            title=params.get("title"),
            link=params.get("link"),
            media=media,
        )
    except NotifyError as e:
        raise ValueError(f"notify send failed: {e}")
    # Passthrough: emit exactly what came in so the chain continues.
    return {"ok": True, "op": "notify", "out": passthrough, "type": wire}


async def _step_clip_generate(inputs: List[str], params: dict) -> dict:
    """clip.generate — assemble input image/video refs into one MP4 (Ken-Burns).

    Inputs: one or more asset refs on stdin (newline-separated). Params:
    resolution, durations, animation (passed to media.create_clip). Output lands
    in the "clipper" store. The blocking ffmpeg work runs in a worker thread.
    """
    if not inputs:
        raise ValueError("clip.generate needs at least one input ref on stdin")
    input_paths = [asset_refs.resolve_ref(r) for r in inputs if r.strip()]
    out_store = "clipper"
    out_name = params.get("name") or f"pipe_{uuid.uuid4().hex[:8]}.mp4"
    out_path = asset_refs.store_root(out_store) / out_name
    clip = await asyncio.to_thread(
        create_clip,
        input_paths,
        out_path,
        resolution=params.get("resolution", "1080p"),
        durations=params.get("durations", "4"),
        animation=params.get("animation", "pan"),
    )
    # Optional soundtrack: lay a resolved audio ref (e.g. a music.generate output)
    # over the assembled clip as its music track, cut to the clip length.
    soundtrack = params.get("soundtrack")
    if soundtrack and str(soundtrack).startswith("asset://"):
        audio_path = asset_refs.resolve_ref(soundtrack)
        if not audio_path.is_file():
            raise ValueError(f"clip.generate: soundtrack not found for ref {soundtrack!r}")
        muxed = asset_refs.store_root(out_store) / f"snd_{out_name}"
        await asyncio.to_thread(mux_audio, clip.path, audio_path, muxed)
        out_ref = asset_refs.ref_for_path(muxed, out_store)
    else:
        out_ref = asset_refs.ref_for_path(clip.path, out_store)
    return {"ok": True, "op": "clip.generate",
            "out": out_ref, "type": "video", "url": asset_refs.url_for_ref(out_ref)}


# Media-finish ops (Welle 3). Each produces a finished media asset ref in its
# own store; blocking encode/render work runs in a worker thread (asyncio.to_thread).
async def _step_text_overlay(inputs: List[str], params: dict) -> dict:
    """text.overlay — render text onto a flat-color background -> image ref.

    Text from ?text= or stdin (an llm step's value). Output lands in the "typer"
    store. Params: size, template, font, fontsize, layout (see media.create_text_frame).
    """
    text = params.get("text") or "\n".join(inputs).strip()
    if not text:
        raise ValueError("text.overlay needs text (?text= or on stdin)")
    out_store = "typer"
    out_name = params.get("name") or f"txt_{uuid.uuid4().hex[:8]}.png"
    out_path = asset_refs.store_root(out_store) / out_name
    asset = await asyncio.to_thread(
        create_text_frame, text, out_path,
        size=params.get("size", "1080x1080"),
        template=params.get("template", "dark"),
        font=params.get("font", "bold"),
        fontsize=params.get("fontsize", "medium"),
        layout=params.get("layout", "left"),
    )
    out_ref = asset_refs.ref_for_path(asset.path, out_store)
    return {"ok": True, "op": "text.overlay",
            "out": out_ref, "type": "image", "url": asset_refs.url_for_ref(out_ref)}


async def _step_gif_create(inputs: List[str], params: dict) -> dict:
    """gif.create — animate one or more image refs into an animated GIF -> ref.

    Inputs: image refs on stdin (newline-separated). Output lands in the "gifer"
    store. Params: durations (per-frame seconds), quality, size.
    """
    if not inputs:
        raise ValueError("gif.create needs at least one image ref on stdin")
    input_paths = [asset_refs.resolve_ref(r) for r in inputs if r.strip()]
    out_store = "gifer"
    out_name = params.get("name") or f"gif_{uuid.uuid4().hex[:8]}.gif"
    out_path = asset_refs.store_root(out_store) / out_name
    asset = await asyncio.to_thread(
        create_gif, input_paths, out_path,
        params.get("durations", "1"),
        quality=params.get("quality", "medium"),
        size=params.get("size"),
    )
    out_ref = asset_refs.ref_for_path(asset.path, out_store)
    return {"ok": True, "op": "gif.create",
            "out": out_ref, "type": "video", "url": asset_refs.url_for_ref(out_ref)}


async def _step_tts_speak(inputs: List[str], params: dict) -> dict:
    """tts.speak — synthesize speech from text -> audio ref.

    Text from ?text= or stdin. The TTS library writes into its own output dir
    (the "tts" store). Params: language, voice, format, engine (->engine_pref), speed.
    """
    text = params.get("text") or "\n".join(inputs).strip()
    if not text:
        raise ValueError("tts.speak needs text (?text= or on stdin)")
    asset = await asyncio.to_thread(
        tts_lib.generate, text,
        language=params.get("language", "en"),
        voice=params.get("voice") or None,  # empty enum choice -> auto by language
        format=params.get("format", "wav"),
        engine_pref=params.get("engine", "auto"),
        speed=float(params["speed"]) if params.get("speed") else 1.0,
    )
    out_ref = asset_refs.ref_for_path(asset.path, "tts")
    return {"ok": True, "op": "tts.speak",
            "out": out_ref, "type": "audio", "url": asset_refs.url_for_ref(out_ref)}


def _walk_path(data, path: str):
    """Follow a dotted path into parsed JSON. Raises ValueError naming where it stopped."""
    current = data
    walked: list[str] = []
    for part in path.split("."):
        where = ".".join(walked) or "the top level"
        walked.append(part)
        if isinstance(current, list):
            try:
                index = int(part)
            except ValueError:
                raise ValueError(
                    f"{where} is a list of {len(current)}, so {part!r} has to be a "
                    "number (0 is the first, -1 the last)"
                )
            try:
                current = current[index]
            except IndexError:
                raise ValueError(
                    f"{where} has {len(current)} entries, so there is no {part!r}"
                )
        elif isinstance(current, dict):
            if part not in current:
                have = ", ".join(list(current)[:8]) or "nothing"
                raise ValueError(f"{where} has no {part!r} — it has: {have}")
            current = current[part]
        else:
            raise ValueError(
                f"{where} is a plain value, so {part!r} cannot be looked up inside it"
            )
    return current


async def _step_data_pick(inputs: List[str], params: dict) -> dict:
    """data.pick — take one value out of an earlier step's JSON.

    The missing joint between ops that EMIT a structure and ops that want single
    values: stock.search returns a list of hits while stock.download wants a
    source and a url, db.insert returns a row while db.get wants its id. Without
    this, those pairs could not be wired at all - the values had to be copied out
    by hand.

    Params: path (dotted, list indices as numbers: ``results.0.url``, ``-1`` for
    the last entry), default (what to emit when the path is not there; without
    it a missing path is an error, because a silently empty value is how a later
    step ends up working on nothing).
    """
    raw = "\n".join(inputs).strip()
    if not raw:
        raise ValueError("data.pick needs JSON on stdin (an earlier step's output)")
    path = params.get("path")
    if not path:
        raise ValueError("data.pick needs ?path= (e.g. results.0.url)")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"data.pick: stdin is not JSON ({e}); got {raw[:80]!r}")

    try:
        value = _walk_path(data, path)
    except ValueError as e:
        if "default" in params:
            return {"ok": True, "op": "data.pick", "out": params["default"], "type": "text",
                    "log": {"path": path, "used_default": True, "why": str(e)}}
        raise ValueError(f"data.pick: {e}")

    # A scalar travels as itself; a branch travels as JSON, so it can be handed on
    # to another data.pick or into db.insert.
    out = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return {"ok": True, "op": "data.pick", "out": out, "type": "text",
            "log": {"path": path, "picked_type": type(value).__name__}}


# Generic table CRUD ops (Welle 5) — thin pipeline wrappers over mora02_core.db.
# Each returns a JSON string on stdout so results chain as values; reads take
# params, writes take their row data from ?data= or stdin (a prior step's JSON).
def _json_from(params: dict, inputs: List[str], key: str = "data"):
    raw = params.get(key) or "\n".join(inputs).strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid JSON for {key!r}: {e}")


async def _step_db_query(inputs: List[str], params: dict) -> dict:
    """db.query — list rows of a table (optional filter/order/size) as JSON."""
    table = params.get("table")
    if not table:
        raise ValueError("db.query needs ?table=")
    filt = None
    if params.get("filter"):
        try:
            filt = json.loads(params["filter"])
        except json.JSONDecodeError as e:
            raise ValueError(f"invalid filter JSON: {e}")
    rows = await db_api.query(
        table, filter=filt, order_by=params.get("order_by"),
        size=int(params.get("size", 50)),
    )
    return {"ok": True, "op": "db.query", "type": "text",
            "out": json.dumps(rows, ensure_ascii=False), "log": {"rows": len(rows)}}


async def _step_db_get(inputs: List[str], params: dict) -> dict:
    """db.get — fetch one row by id as JSON."""
    table, rid = params.get("table"), params.get("row_id")
    if not table or not rid:
        raise ValueError("db.get needs ?table= and ?row_id=")
    row = await db_api.get(table, int(rid))
    return {"ok": True, "op": "db.get", "type": "text",
            "out": json.dumps(row, ensure_ascii=False)}


async def _step_db_insert(inputs: List[str], params: dict) -> dict:
    """db.insert — create a row from ?data= or stdin JSON; returns the row."""
    table = params.get("table")
    if not table:
        raise ValueError("db.insert needs ?table=")
    data = _json_from(params, inputs)
    if not isinstance(data, dict):
        raise ValueError("db.insert needs JSON field values (?data= or on stdin)")
    row = await db_api.insert(table, data)
    return {"ok": True, "op": "db.insert", "type": "text",
            "out": json.dumps(row, ensure_ascii=False)}


async def _step_db_update(inputs: List[str], params: dict) -> dict:
    """db.update — patch a row by id from ?data= or stdin JSON."""
    table, rid = params.get("table"), params.get("row_id")
    if not table or not rid:
        raise ValueError("db.update needs ?table= and ?row_id=")
    data = _json_from(params, inputs)
    if not isinstance(data, dict):
        raise ValueError("db.update needs JSON field values (?data= or on stdin)")
    row = await db_api.update(table, int(rid), data)
    return {"ok": True, "op": "db.update", "type": "text",
            "out": json.dumps(row, ensure_ascii=False)}


async def _step_db_delete(inputs: List[str], params: dict) -> dict:
    """db.delete — delete a row by id."""
    table, rid = params.get("table"), params.get("row_id")
    if not table or not rid:
        raise ValueError("db.delete needs ?table= and ?row_id=")
    ok = await db_api.delete(table, int(rid))
    return {"ok": True, "op": "db.delete", "type": "text",
            "out": json.dumps({"deleted": ok})}


async def _step_db_list_fields(inputs: List[str], params: dict) -> dict:
    """db.list_fields — the table's field schema as JSON."""
    table = params.get("table")
    if not table:
        raise ValueError("db.list_fields needs ?table=")
    fields = await db_api.list_fields(table)
    return {"ok": True, "op": "db.list_fields", "type": "text",
            "out": json.dumps(fields, ensure_ascii=False)}


# Web + stock ops (Welle 6). The searching and reading themselves live in
# mora02_core.web -- the agent layer's MCP surface needs the same two calls, and
# that module is imported BY this one, so it cannot import back. Logic once
# (ADR-011); what stays here is the step contract around it.


async def _step_web_search(inputs: List[str], params: dict) -> dict:
    """web.search — query the local SearXNG; returns top results as JSON text."""
    query = params.get("query") or "\n".join(inputs).strip()
    if not query:
        raise ValueError("web.search needs a query (?query= or on stdin)")
    try:
        found = await web.search(query, categories=params.get("categories", "general"))
    except web.WebError as e:
        raise ValueError(str(e)) from e
    return {"ok": True, "op": "web.search", "type": "text",
            "out": json.dumps(found, ensure_ascii=False),
            "log": {"results": len(found["results"])}}


async def _step_web_fetch(inputs: List[str], params: dict) -> dict:
    """web.fetch — fetch a URL and return its readable text (HTML stripped, capped)."""
    url = params.get("url") or "\n".join(inputs).strip()
    if not url:
        raise ValueError("web.fetch needs a url (?url= or on stdin)")
    try:
        page = await web.fetch(url, max_chars=int(params.get("max_chars") or 20000))
    except web.WebError as e:
        raise ValueError(str(e)) from e
    # The step's log keeps the shape the run log and the Runs view already read,
    # truncation flag and hint included.
    text = page.pop("text")
    return {"ok": True, "op": "web.fetch", "type": "text", "out": text, "log": page}


async def _stock_search(source: str, query: str, count: int, orientation: str) -> list:
    """Search Pexels/Pixabay; returns [{id, thumbnail, url, photographer, ...}]."""
    import urllib.parse
    q = urllib.parse.quote(query)
    async with httpx.AsyncClient(timeout=15.0) as client:
        if source == "pexels":
            if not PEXELS_API_KEY:
                raise ValueError("stock.search pexels: PEXELS_API_KEY not set")
            url = f"https://api.pexels.com/v1/search?query={q}&per_page={count}&orientation={orientation}"
            resp = await client.get(url, headers={"Authorization": PEXELS_API_KEY})
            resp.raise_for_status()
            return [
                {"id": str(p["id"]),
                 "thumbnail": p["src"].get("medium", p["src"].get("small")),
                 "url": p["src"].get("original", p["src"].get("large2x")),
                 "photographer": p.get("photographer", "Unknown"),
                 "width": p.get("width"), "height": p.get("height")}
                for p in resp.json().get("photos", [])
            ]
        if source == "pixabay":
            if not PIXABAY_API_KEY:
                raise ValueError("stock.search pixabay: PIXABAY_API_KEY not set")
            omap = {"landscape": "horizontal", "portrait": "vertical", "square": "all"}
            o = omap.get(orientation, "horizontal")
            url = (f"https://pixabay.com/api/?key={PIXABAY_API_KEY}&q={q}&per_page={count}"
                   f"&orientation={o}&image_type=photo&safesearch=true")
            resp = await client.get(url)
            resp.raise_for_status()
            return [
                {"id": str(h["id"]),
                 "thumbnail": h.get("webformatURL", h.get("previewURL")),
                 "url": h.get("fullHDURL") or h.get("largeImageURL") or h.get("webformatURL"),
                 "photographer": h.get("user", "Unknown"),
                 "width": h.get("imageWidth"), "height": h.get("imageHeight")}
                for h in resp.json().get("hits", [])
            ]
    raise ValueError(f"unknown stock source {source!r}")


async def _step_stock_search(inputs: List[str], params: dict) -> dict:
    """stock.search — search Pexels/Pixabay; returns candidates (id+url) as JSON."""
    query = params.get("query") or "\n".join(inputs).strip()
    if not query:
        raise ValueError("stock.search needs a query (?query= or on stdin)")
    source = params.get("source", "pexels")
    results = await _stock_search(
        source, query, int(params.get("count", 5)),
        params.get("orientation", "landscape"),
    )
    return {"ok": True, "op": "stock.search", "type": "text",
            "out": json.dumps({"source": source, "query": query, "results": results}, ensure_ascii=False),
            "log": {"source": source, "results": len(results)}}


async def _step_stock_download(inputs: List[str], params: dict) -> dict:
    """stock.download — download a stock image into the 'stock' store -> image ref."""
    source = params.get("source")
    image_url = params.get("image_url")
    if not source or not image_url:
        raise ValueError("stock.download needs ?source= and ?image_url=")
    image_id = params.get("image_id") or uuid.uuid4().hex[:8]
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        resp = await client.get(image_url, headers={"User-Agent": "Mozilla/5.0 (mora02 pipeline)"})
        resp.raise_for_status()
        ctype = resp.headers.get("content-type", "")
        data = resp.content
    ext = ".png" if "png" in ctype else (".webp" if "webp" in ctype else ".jpg")
    out_store = "stock"
    out_name = f"stock_{source}_{image_id}{ext}"
    out_path = asset_refs.store_root(out_store) / out_name
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    out_ref = asset_refs.make_ref(out_store, out_name)
    return {"ok": True, "op": "stock.download", "out": out_ref, "type": "image",
            "url": asset_refs.url_for_ref(out_ref), "log": {"source": source, "bytes": len(data)}}


# Step registry. Every handler is async (see section header). New ops land here.
async def _step_llm_switch(inputs: List[str], params: dict) -> dict:
    """llm.switch — swap the active local LLM (llama.cpp profile), like the Pilot
    model switcher, then pass stdin through unchanged so the chain continues.

    Reuses the file-mailbox switcher (the same path the Pilot button and
    POST /llm/switch use): a request file is written, a root host unit performs
    the docker profile swap, and we block until it reports done (~10-20s). The
    switch is GLOBAL and persistent — it changes the model for the whole box, not
    just this pipeline; there is no auto switch-back (place a second llm.switch to
    restore). Param: profile (required; validated against the catalog here and
    against the vocab enum at compile time).
    """
    profile = params.get("profile")
    if not profile:
        raise ValueError("llm.switch needs a profile (?profile=)")
    if profile not in llm_valid_profile_names():
        raise ValueError(
            f"llm.switch: unknown profile {profile!r}; "
            f"valid: {sorted(llm_valid_profile_names())}"
        )
    # switch_profile_blocking polls with time.sleep — run it off the event loop.
    try:
        await asyncio.to_thread(llm_switch_blocking, profile, 120.0)
    except LLMSwitchError as e:
        raise ValueError(f"llm.switch failed: {e}")
    # Passthrough: emit exactly what came in so the chain continues. stdin
    # arrives split into lines, so rejoin — a ref survives either way, a text
    # value would otherwise lose everything after its first paragraph.
    incoming = "\n".join(inputs).strip()
    return {"ok": True, "op": "llm.switch", "out": incoming, "type": "any"}


_LINKEDIN_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                  ".gif": "image/gif", ".webp": "image/webp"}


async def _step_publish_linkedin(inputs: List[str], params: dict) -> dict:
    """publish.linkedin — post an image (from a stdin ref) or text to LinkedIn.

    An asset:// ref on stdin is resolved to its file and posted as an image share;
    without a ref it is a text-only post. Caption from ?text= (often a
    {"from": <llm step>} ref). Token + default author come from the environment
    (MORA02_LINKEDIN_TOKEN / MORA02_LINKEDIN_AUTHOR). Returns the post URL. This has
    a REAL side effect: it publishes publicly. The AP-flow's gate/Baserow-writeback
    are composed in the pipeline (review + db.update), not baked into this op.
    """
    # An asset ref is one line; post text is not. Keep the first line for the
    # ref check, but use the whole input as the text body.
    incoming = inputs[0] if inputs else ""
    body_text = "\n".join(inputs).strip()
    image_bytes = None
    image_mime = "image/png"
    if incoming.startswith("asset://"):
        path = asset_refs.resolve_ref(incoming)
        if not path.is_file():
            raise ValueError(f"publish.linkedin: image not found for ref {incoming!r}")
        image_bytes = path.read_bytes()
        image_mime = _LINKEDIN_MIME.get(path.suffix.lower(), "image/png")

    text = params.get("text") or ("" if incoming.startswith("asset://") else body_text)
    author = params.get("author") or os.environ.get("MORA02_LINKEDIN_AUTHOR")
    token = os.environ.get("MORA02_LINKEDIN_TOKEN")
    if not token:
        raise ValueError("publish.linkedin needs MORA02_LINKEDIN_TOKEN in the environment")
    if not author:
        raise ValueError("publish.linkedin needs an author (?author= or MORA02_LINKEDIN_AUTHOR)")
    if not text and image_bytes is None:
        raise ValueError("publish.linkedin needs ?text= or an image ref on stdin")

    try:
        result = await post_to_linkedin(
            token=token, author=author, text=text or "",
            image_bytes=image_bytes, image_mime=image_mime,
            visibility=params.get("visibility", "PUBLIC"),
        )
    except LinkedInError as e:
        raise ValueError(f"publish.linkedin failed: {e}")
    return {"ok": True, "op": "publish.linkedin", "out": result["post_url"],
            "type": "text", "log": {"post_id": result["post_id"]}}


# PixelText 3D typography. Unlike the other media ops (which call a mora02_core
# lib), this one POSTs to the standalone blender-worker service (GPU render),
# mirroring the reference caller apps/pilot/bot_bridge.py::call_pixeltext.
BLENDER_WORKER_URL = "http://blender-worker:8097"


async def _step_pixeltext_render(inputs: List[str], params: dict) -> dict:
    """pixeltext.render — 3D pixel-cube text animation via the Blender worker.

    Text from ?text= or stdin. In multi mode the text is split on '/' into a word
    sequence. Slim param surface (mode/template/format/colors/duration); all other
    look knobs fall back to the worker's template defaults. Returns an MP4 (or PNG)
    ref in the 'pixeltext' store (files land under <job_id>/<file>).
    """
    text = (params.get("text") or "\n".join(inputs)).strip()
    if not text:
        raise ValueError("pixeltext.render needs text (?text= or on stdin)")
    mode = params.get("mode", "single")
    if mode == "multi":
        words = [w.strip().upper() for w in text.split("/") if w.strip()]
    else:
        words = [text.upper()]
    if not words:
        raise ValueError("pixeltext.render got no renderable words")

    config = {
        "mode": mode,
        "words": words,
        "text": words[0] if mode == "single" else "",
        "render_format": params.get("render_format", "MP4"),
    }
    if params.get("template"):
        config["template"] = params["template"]
    if params.get("cube_color"):
        config["cube_color"] = params["cube_color"]
    if params.get("bg_color"):
        config["bg_color"] = params["bg_color"]
    if params.get("duration"):
        config["single_duration_sec"] = int(params["duration"])
    # Single-mode motion toggles (bool params arrive as strings). Without one of
    # these a single word renders motionless; multi mode animates on its own.
    for eff in ("effect_pulse", "effect_float", "effect_shuffle"):
        if params.get(eff) is not None:
            config[eff] = str(params[eff]).strip().lower() in ("1", "true", "on", "yes")

    async with httpx.AsyncClient(timeout=900.0) as client:
        resp = await client.post(
            f"{BLENDER_WORKER_URL}/render",
            files={"config": (None, json.dumps(config))},
        )
    data = resp.json()
    if not data.get("success"):
        # VRAM guard (503) and Blender render errors both arrive as success=false.
        raise ValueError(f"pixeltext render failed: {str(data.get('error', 'unknown'))[:500]}")
    files_out = data.get("files") or []
    if not files_out:
        raise ValueError("pixeltext render produced no output files")

    job_id = data["job_id"]
    out_ref = asset_refs.make_ref("pixeltext", f"{job_id}/{files_out[0]}")
    out_type = "image" if files_out[0].lower().endswith(".png") else "video"
    return {"ok": True, "op": "pixeltext.render", "out": out_ref, "type": out_type,
            "url": asset_refs.url_for_ref(out_ref),
            "log": {"job_id": job_id, "mode": mode, "words": words,
                    "render_time_sec": data.get("render_time_sec")}}


_PIPELINE_STEPS = {
    "image.edit": _step_image_edit,
    "image.cutout": _step_image_cutout,
    "image.erase": _step_image_erase,
    "image.facefix": _step_image_facefix,
    "source.file": _step_source_file,
    "source.find": _step_source_find,
    "llm.image_prompt": _step_llm_image_prompt,
    "llm.complete": _step_llm_complete,
    "llm.summarize": _step_llm_summarize,
    "llm.classify": _step_llm_classify,
    "llm.extract": _step_llm_extract,
    "llm.translate": _step_llm_translate,
    "llm.switch": _step_llm_switch,
    "image.generate": _step_image_generate,
    "image.upscale": _step_image_upscale,
    "image.expand": _step_image_expand,
    "video.generate": _step_video_generate,
    "video.last_frame": _step_video_last_frame,
    "notify.image": _step_notify_image,
    "notify": _step_notify,
    "publish.linkedin": _step_publish_linkedin,
    "clip.generate": _step_clip_generate,
    "text.overlay": _step_text_overlay,
    "gif.create": _step_gif_create,
    "tts.speak": _step_tts_speak,
    "music.generate": _step_music_generate,
    "pixeltext.render": _step_pixeltext_render,
    "data.pick": _step_data_pick,
    "db.query": _step_db_query,
    "db.get": _step_db_get,
    "db.insert": _step_db_insert,
    "db.update": _step_db_update,
    "db.delete": _step_db_delete,
    "db.list_fields": _step_db_list_fields,
    "web.search": _step_web_search,
    "web.fetch": _step_web_fetch,
    "stock.search": _step_stock_search,
    "stock.download": _step_stock_download,
    "cloud.complete": _step_cloud_complete,
    "cloud.vision": _step_cloud_vision,
}

# Drift guard: the implemented handlers here and the structural vocabulary in
# mora02_core.pipeline.vocab must describe the SAME ops. If they diverge, a spec
# would compile (validated against vocab) but fail at runtime (no handler), or an
# op would be runnable but invisible to the authoring front-ends. Warn loudly at
# import so the mismatch surfaces on the next deploy, not in a broken pipeline.
# Only "wired" vocab ops must have a handler here; "planned" ops are catalogued
# in the vocabulary on purpose and intentionally have none yet.
_wired_names = pipeline_vocab.wired_op_names()
_handler_names = set(_PIPELINE_STEPS)
if _wired_names != _handler_names:
    _log.warning(
        "pipeline vocab/handler drift — handler-only: %s | wired-vocab-only: %s",
        sorted(_handler_names - _wired_names),
        sorted(_wired_names - _handler_names),
    )


# ---------------------------------------------------------------------------
# What the vocabulary COSTS in practice - measured, not declared.
#
# vocab.py states what cannot be measured: where an op runs, whether money moves,
# whether it can be undone. Everything else a human wants before putting an op in
# a loop - how long it really takes, when it last worked, what it has actually
# cost - is in the run log, and a number typed into a table by hand ages into a
# lie. So it is read back out of what really happened.
# ---------------------------------------------------------------------------

_VOCAB_STATS_CACHE: dict = {"signature": None, "payload": None}


def _spec_op_usage() -> dict:
    """op name -> [flow names that use it], read from the saved library."""
    usage: dict[str, list] = {}
    specs = Path(_PIPELINE_SPECS_DIR)
    if not specs.is_dir():
        return usage
    for path in sorted(specs.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for raw in data.get("steps") or []:
            if isinstance(raw, dict) and len(raw) == 1:
                op = next(iter(raw))
                if op not in ("gate", "review"):
                    usage.setdefault(op, []).append(path.stem)
    return usage


def _median(values: list) -> Optional[int]:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return int(ordered[middle])
    return int((ordered[middle - 1] + ordered[middle]) / 2)


@app.get("/pipeline/vocab-stats")
async def pipeline_vocab_stats(window_days: int = 30):
    """Per-op reality: how often, how long, how much, when last, where it lands.

    Read from the run logs on every call (cached against the directory's state),
    so it cannot drift from what the machine actually did.
    """
    log_dir = Path(pipeline_runlog.log_dir())
    files = sorted(log_dir.glob("*.jsonl")) if log_dir.is_dir() else []
    signature = (len(files), max((f.stat().st_mtime for f in files), default=0), window_days)
    if _VOCAB_STATS_CACHE["signature"] == signature:
        return _VOCAB_STATS_CACHE["payload"]

    cutoff = time.time() - window_days * 86400
    stats: dict = {}
    scanned = 0
    for path in files:
        scanned += 1
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue  # a half-written line must not cost the whole answer
            if event.get("kind") != "step":
                continue
            op = event.get("op")
            if not op:
                continue
            entry = stats.setdefault(op, {"runs": 0, "ok": 0, "failed": 0, "last_ok": None,
                                          "durations": [], "spend_usd": 0.0, "stores": []})
            entry["runs"] += 1
            status = event.get("status")
            if status == "ok":
                entry["ok"] += 1
                ts = event.get("ts")
                if ts and (entry["last_ok"] is None or ts > entry["last_ok"]):
                    entry["last_ok"] = ts
                if isinstance(event.get("duration_ms"), (int, float)):
                    entry["durations"].append(event["duration_ms"])
                out = event.get("out")
                if isinstance(out, str) and out.startswith("asset://"):
                    store = out[len("asset://"):].split("/", 1)[0]
                    if store and store not in entry["stores"]:
                        entry["stores"].append(store)
            elif status == "failed":
                entry["failed"] += 1
            cost = event.get("cost_usd")
            if isinstance(cost, (int, float)):
                stamp = event.get("ts") or ""
                # Cheap window check: the log stamps are ISO, so a string compare
                # against the cutoff's ISO form is enough and needs no parsing.
                if not stamp or stamp >= datetime.fromtimestamp(cutoff, timezone.utc).isoformat():
                    entry["spend_usd"] += float(cost)

    usage = _spec_op_usage()
    ops_out = {}
    for op, entry in stats.items():
        ops_out[op] = {
            "runs": entry["runs"],
            "ok": entry["ok"],
            "failed": entry["failed"],
            "last_ok": entry["last_ok"],
            "median_ms": _median(entry["durations"]),
            "spend_eur": pricing.to_eur(entry["spend_usd"]) if entry["spend_usd"] else 0.0,
            "stores": entry["stores"],
            "used_by": usage.get(op, []),
        }
    for op, flows in usage.items():
        ops_out.setdefault(op, {"runs": 0, "ok": 0, "failed": 0, "last_ok": None,
                                "median_ms": None, "spend_eur": 0.0, "stores": [],
                                "used_by": flows})

    payload = {
        "window_days": window_days,
        "scanned_runs": scanned,
        "rate": {"usd_eur": pricing.usd_eur(), "date": pricing.RATE_DATE,
                 "note": pricing.rate_note()},
        "models": [
            {"key": key,
             "name": cfg.get("name"),
             "in_eur_per_1m": pricing.to_eur(cfg.get("cost_input_per_1m")),
             "out_eur_per_1m": pricing.to_eur(cfg.get("cost_output_per_1m"))}
            for key, cfg in llm_models.MODELS.items()
            if cfg.get("cost_input_per_1m")
        ],
        "ops": ops_out,
    }
    _VOCAB_STATS_CACHE.update(signature=signature, payload=payload)
    return payload


@app.get("/pipeline/ops")
async def pipeline_ops():
    """The pipeline step vocabulary — ops with their params, types, and defaults.

    Single source of truth from mora02_core.pipeline.vocab. Consumed by the
    authoring front-ends (visual builder / recording / LLM dialog) to enumerate
    and validate available steps; the compiler validates specs against the same.
    """
    return pipeline_vocab.to_dict()


def _ref_name(value):
    """Filename tail of an asset ref (asset://store/name) — None for non-refs."""
    if isinstance(value, str) and value.startswith("asset://"):
        return value.rsplit("/", 1)[-1]
    return None


_LOG_VALUE_MAX = 200  # per-input value budget in the run log


def _log_inputs(inputs: List[str]) -> list:
    """Compact per-input record for the run log: ref+name, or a value.

    A shortened value SAYS SO. The run log is what a human reads when hunting a
    defect, and a line silently cut to 200 characters shows a different input
    than the one that ran - with nothing to tell the reader that the rest
    existed. The flag and the true length cost nothing and keep the record
    honest; the cut itself stays, because a run log is not an archive.
    """
    out = []
    for x in inputs:
        name = _ref_name(x)
        if name:
            out.append({"ref": x, "name": name})
        elif len(x) > _LOG_VALUE_MAX:
            out.append({"value": x[:_LOG_VALUE_MAX], "truncated": True, "len": len(x)})
        else:
            out.append({"value": x})
    return out


def _fail_wiring(run_id, step_id: str, op: str, params: dict, detail: str):
    """Refuse a step whose wiring points at a step that produced nothing.

    Logs before it raises. These two checks run BEFORE the handler, so they used
    to skip the run log entirely: the server answered 400 with a good reason,
    and the RUNS view showed nothing at all - the run simply stopped after its
    last successful step. A mis-wired reference is the likeliest mistake anyone
    makes in the flow builder, so it is the last failure that should be invisible.
    """
    pipeline_runlog.log_event(
        run_id, "step", step_id=step_id, op=op, params=params,
        status="failed", error=detail, duration_ms=0,
    )
    raise HTTPException(status_code=400, detail=detail)


@app.post("/pipeline/step/{op}")
async def pipeline_step(op: str, request: Request):
    """Execute one pipeline step. See the section header for the contract."""
    handler = _PIPELINE_STEPS.get(op)
    if handler is None:
        raise HTTPException(status_code=404, detail=f"unknown step op {op!r}")

    body = (await request.body()).decode("utf-8", "replace")
    # Keep BLANK lines: a ref is still the first line, but a text value carries
    # its paragraphs in them, and a handler that rejoins with "\n" would
    # otherwise hand on one dense block. Only the outer padding is dropped.
    inputs = [ln.rstrip() for ln in body.splitlines()]
    while inputs and not inputs[0]:
        inputs.pop(0)
    while inputs and not inputs[-1]:
        inputs.pop()
    params = dict(request.query_params)
    fmt = params.pop("fmt", None)
    # run_id/step_id are baked by the compiler for run-log correlation, not by
    # the handler — pop them so they don't reach the op as stray params.
    run_id = params.pop("run_id", None)
    step_id = params.pop("step_id", op)
    # The customer/project axis. Baked by the compiler like run_id, not a param
    # the op sees: it narrows which library paths this step may touch at all,
    # and it does that below the ops rather than inside each of them (see
    # mora02_core.assets.scope).
    project = params.pop("project", None)
    # Resolve step-output references: a compiled ref param arrives as
    # __ref_<param>=<source step id>; pull that earlier step's output from the run
    # bucket into the real param before the handler runs (non-linear fan-in, so a
    # step can take e.g. its prompt from one prior step and lyrics from another).
    for key in [k for k in params if k.startswith("__ref_")]:
        source_id = params.pop(key)
        pname = key[len("__ref_"):]
        try:
            params[pname] = pipeline_runbucket.get(run_id, source_id)
        except KeyError:
            _fail_wiring(
                run_id, step_id, op, params,
                f"step {op}: param {pname!r} references step {source_id!r}, "
                "which has no output in the run bucket (did it run first?)",
            )
    # Input fan-in: __collect=a,b,c pulls several earlier step outputs from the run
    # bucket and hands them to a "many"-consuming op (e.g. clip.generate) as its inputs.
    collect = params.pop("__collect", None)
    if collect:
        try:
            inputs = [pipeline_runbucket.get(run_id, cid) for cid in collect.split(",") if cid]
        except KeyError as e:
            _fail_wiring(
                run_id, step_id, op, params,
                f"step {op}: collect source {e} has no output in the run bucket",
            )
    started = time.monotonic()

    # A border thirty verbs each have to remember is not a border, so it is
    # held here: inside this block a library ref outside the project's folder
    # cannot be produced or resolved, whichever op is running.
    step_scope = (asset_refs.scope({"library": f"{project}/"})
                  if project else nullcontext())

    try:
        with step_scope:
            result = await handler(inputs, params)
    except (asset_refs.AssetRefError, MediaError, ValueError, FileNotFoundError) as e:
        pipeline_runlog.log_event(
            run_id, "step", step_id=step_id, op=op, params=params,
            inputs=_log_inputs(inputs), status="failed", error=str(e),
            duration_ms=round((time.monotonic() - started) * 1000),
        )
        raise HTTPException(status_code=400, detail=f"step {op} failed: {e}")
    except Exception as e:
        # Any other failure (upstream API/node error, timeout, unexpected response
        # shape) must not 500 the service — a step failing is a workflow event, not
        # a server fault. Log the full traceback for debugging, then return a clean
        # 400 so the runner aborts the workflow gracefully (as the validation path
        # above does). curl -fsS in the compiled step sees the non-2xx and stops.
        _log.exception("pipeline step %s raised an unexpected error", op)
        pipeline_runlog.log_event(
            run_id, "step", step_id=step_id, op=op, params=params,
            inputs=_log_inputs(inputs), status="failed",
            error=f"{type(e).__name__}: {e}",
            duration_ms=round((time.monotonic() - started) * 1000),
        )
        raise HTTPException(status_code=400, detail=f"step {op} failed: {type(e).__name__}: {e}")

    out = result.get("out")
    # Publish this step's output to the run bucket so later steps can pull it into
    # a specific param via a {"from": "<id>"} reference (non-linear fan-in).
    pipeline_runbucket.put(run_id, step_id, out)
    # A handler may attach a "log" dict of extra per-step fields (e.g. LLM token
    # usage); merge it into the step event so the run log captures it. Generic on
    # purpose — future ops (image seed/model, …) use the same channel.
    extra = result.get("log") or {}
    # A handler's own log fields must not be able to break the step. log_event's
    # signature already owns "kind", and the call below owns the rest; a colliding
    # key raises TypeError - AFTER the handler ran and outside its try block, so
    # the work is done, the value is in the bucket, and the caller gets a bare 500
    # with no reason. An op that names a field badly is a naming mistake; losing
    # the run over it is a design mistake. The op's key is dropped, and the drop
    # is recorded rather than hidden.
    _reserved = {"kind", "run_id", "step_id", "op", "params", "inputs", "out",
                 "out_name", "out_type", "status", "duration_ms", "error"}
    clashes = sorted(set(extra) & _reserved)
    extra = {k: v for k, v in extra.items() if k not in _reserved}
    if clashes:
        extra["log_field_clash"] = clashes
        _log.warning("op %s attaches reserved log field(s) %s - dropped", op, clashes)
    pipeline_runlog.log_event(
        run_id, "step", step_id=step_id, op=op, params=params,
        inputs=_log_inputs(inputs), out=out, out_name=_ref_name(out),
        out_type=result.get("type"), status="ok",
        duration_ms=round((time.monotonic() - started) * 1000),
        **extra,
    )

    if fmt in ("ref", "out", "text"):
        return PlainTextResponse(result["out"])
    return result


@app.post("/pipeline/replay")
async def pipeline_replay(from_run: str, step: str, run_id: str = None,
                          step_id: str = None, fmt: str = "out"):
    """Re-emit a stored output of an earlier run instead of doing the work again.

    The cheap half of a partial re-run: a step whose inputs did not change keeps
    its result. The value is copied into THIS run's bucket under the same id, so
    everything downstream resolves exactly as if the step had really run — the
    difference is invisible to the rest of the pipeline, and visible in the run
    log, where the step is marked ``replayed``.
    """
    try:
        out = pipeline_runbucket.get(from_run, step)
    except KeyError:
        # Not a crash-worthy bug: the earlier run may have been pruned, or never
        # got that far. Say which run and which step -- curl surfaces the body.
        raise HTTPException(
            status_code=400,
            detail=f"replay: run {from_run!r} has no stored output for step {step!r}",
        )
    pipeline_runbucket.put(run_id, step_id or step, out)
    pipeline_runlog.log_event(
        run_id, "step", step_id=step_id or step, op="replay", params={"from_run": from_run},
        out=out, out_name=_ref_name(out), status="replayed", duration_ms=0,
    )
    if fmt in ("ref", "out", "text"):
        return PlainTextResponse(out if isinstance(out, str) else json.dumps(out))
    return {"ok": True, "out": out, "replayed_from": from_run}


# ============================================================================
# ENDPOINTS - TTS (Text-to-Speech)
# ============================================================================
# Routes speech-synthesis requests to one of three TTS backends (piper, kokoro,
# chatterbox) via the mora02_core.media.tts library. The previous home was the
# knowledge-api service, dissolved per ADR-020.

class TTSGenerateRequest(BaseModel):
    text: str
    language: str = "en"
    voice: Optional[str] = None
    format: str = "wav"
    engine: str = "auto"  # auto / piper / kokoro / chatterbox
    speed: float = 1.0
    noise_scale: float = 0.667
    noise_w: float = 0.8
    exaggeration: float = 0.5
    cfg_weight: float = 0.5
    temperature: float = 0.8
    cb_voice: str = ""


@app.get("/tts/voices")
async def tts_voices():
    """List available TTS voices grouped by language."""
    return tts_lib.list_voices()


@app.get("/tts/health")
async def tts_health():
    """Quick health-poll of kokoro and piper backends."""
    return tts_lib.check_backends()


@app.post("/tts/generate")
async def tts_generate(request: TTSGenerateRequest):
    """Generate speech audio from text — engine routing in the library."""
    try:
        asset = tts_lib.generate(
            text=request.text,
            language=request.language,
            voice=request.voice,
            format=request.format,
            engine_pref=request.engine,
            speed=request.speed,
            noise_scale=request.noise_scale,
            noise_w=request.noise_w,
            exaggeration=request.exaggeration,
            cfg_weight=request.cfg_weight,
            temperature=request.temperature,
            cb_voice=request.cb_voice,
        )
    except MediaError as e:
        # Keep the original error-shape the frontend already handles
        return JSONResponse(
            status_code=502 if "timed out" in str(e) or "returned" in str(e) else 400,
            content={"status": "error", "message": str(e)},
        )

    return {
        "success": True,
        **asset.metadata,  # url, filename, voice, engine, language, text_length
    }


@app.get("/tts/voices/library")
async def tts_voice_library():
    """List voices stored in the Chatterbox voice library."""
    return tts_lib.voice_library_list()


@app.post("/tts/voices/upload")
async def tts_voice_upload(
    file: UploadFile = File(...),
    voice_name: str = Form(...),
    language: str = Form("de"),
):
    """Convert an uploaded audio/video file to WAV and register it as a voice."""
    audio_bytes = await file.read()
    try:
        return tts_lib.voice_library_upload(
            voice_name=voice_name,
            audio_bytes=audio_bytes,
            source_filename=file.filename or "upload",
            language=language,
        )
    except MediaError as e:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": str(e)},
        )


@app.delete("/tts/voices/delete/{voice_name}")
async def tts_voice_delete(voice_name: str):
    """Delete a voice from the Chatterbox library."""
    try:
        return tts_lib.voice_library_delete(voice_name)
    except MediaError as e:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": str(e)},
        )


@app.get("/tts/chatterbox/status")
async def tts_chatterbox_status():
    """Check if chatterbox-tts container is running and healthy.

    Uses ``docker inspect`` — script-runner has /var/run/docker.sock mounted
    for this and the start/stop endpoints (see compose).
    """
    try:
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Status}}", "chatterbox-tts"],
            capture_output=True, text=True, timeout=10,
        )
        container_status = result.stdout.strip() if result.returncode == 0 else "not_found"
        healthy = container_status == "running" and tts_lib.chatterbox_health()
        return {
            "container": container_status,
            "healthy": healthy,
            "running": container_status == "running",
        }
    except Exception as e:
        return {"container": "error", "healthy": False, "running": False, "error": str(e)}


@app.post("/tts/chatterbox/start")
async def tts_chatterbox_start():
    """Start the chatterbox-tts container."""
    try:
        result = subprocess.run(
            ["docker", "start", "chatterbox-tts"],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            return JSONResponse(
                status_code=500,
                content={"status": "error", "message": result.stderr[:500]},
            )
        return {"status": "ok", "message": "Chatterbox starting (model warmup may take 1-2 min)"}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)},
        )


@app.post("/tts/chatterbox/stop")
async def tts_chatterbox_stop():
    """Stop the chatterbox-tts container."""
    try:
        result = subprocess.run(
            ["docker", "stop", "chatterbox-tts"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return JSONResponse(
                status_code=500,
                content={"status": "error", "message": result.stderr[:500]},
            )
        return {"status": "ok", "message": "Chatterbox stopped"}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)},
        )
