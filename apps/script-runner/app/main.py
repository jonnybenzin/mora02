#!/usr/bin/env python3
"""
Mora02 Script Runner API
FastAPI service for gifer, clipper, typer scripts
"""

import uuid
import shutil
import subprocess
import httpx
from pathlib import Path
from datetime import datetime
from typing import Optional, List
from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from mora02_core import auth
from mora02_core._common import get_logger
from mora02_core.baserow import api as baserow_api
from mora02_core.media import tts as tts_lib
from mora02_core.media import MediaError
from mora02_core.pipeline import run_pipeline, resume_pipeline, PipelineError

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
    """Create entry in Baserow sb_assets table via mora02_core.baserow.api."""
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
        return await baserow_api.insert("sb_assets", data)
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


class PipelineResumeRequest(BaseModel):
    token: str                      # resumeToken handed back by a paused run
    response: Optional[dict] = None # structured answer for an input: gate
    approve: Optional[bool] = None  # yes/no for an approval: gate
    cancel: bool = False            # cancel the workflow instead of continuing
    runner: Optional[str] = None


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


@app.post("/pipeline/resume")
async def pipeline_resume(req: PipelineResumeRequest):
    """Resume a paused workflow with the external decision (Pilot inbox click)."""
    try:
        res = await resume_pipeline(
            req.token,
            response=req.response,
            approve=req.approve,
            cancel=req.cancel,
            runner=req.runner,
        )
    except PipelineError as e:
        raise HTTPException(status_code=502, detail=f"pipeline runner error: {e}")
    return _pipeline_result_to_dict(res)


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
