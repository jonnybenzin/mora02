#!/usr/bin/env python3
"""
Mora02 Script Runner API
FastAPI service for gifer, clipper, typer scripts
"""

import os
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

# ============================================================================
# CONFIG
# ============================================================================

DATA_DIR = Path("/data")
WIP_DIR = DATA_DIR / "wip"
FINAL_DIR = DATA_DIR / "final"
SCRIPTS_DIR = Path("/app/scripts")

# Path mapping (container → host)
CONTAINER_DATA_PATH = "/data"
HOST_DATA_PATH = "/opt/mora02/output/_default/script-bot"

# Publish destinations (container paths)
PUBLISH_DESTINATIONS = {
    "socialmedia": Path("/socialmedia-assets"),  # Mounted volume
}

# nginx-images URL for assets
NGINX_BASE_URL = "http://mora02.local:8092/script-bot-assets"

# Baserow config
BASEROW_API_URL = "http://baserow:80/api/database/rows/table/568/"
BASEROW_TOKEN = "***BASEROW_TOKEN_OLD_REVOKED***"
BASEROW_HOST = "mora02.local:8085"

# Stock photo APIs
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")
PIXABAY_API_KEY = os.environ.get("PIXABAY_API_KEY", "")

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
    """Create timestamp for filenames"""
    return datetime.now().strftime("%y%m%d%H%M")

def container_to_host_path(container_path: str) -> str:
    """Convert container path to host path"""
    return container_path.replace(CONTAINER_DATA_PATH, HOST_DATA_PATH)

def get_nginx_url(script_type: str, folder: str, filename: str) -> str:
    """Get nginx URL for asset"""
    return f"{NGINX_BASE_URL}/{script_type}/{folder}/{filename}"

async def create_baserow_entry(script_type: str, folder: str, files: List[str], host_path: str):
    """Create entry in Baserow script-bot_assets table"""
    try:
        # Build preview URL (first file)
        first_file = files[0] if files else ""
        preview_url = get_nginx_url(script_type, folder, first_file)
        
        # Prepare data (field names lowercase as per Baserow API)
        data = {
            "type": script_type,
            "path": host_path,
            "filename": ", ".join(files),
            "files_count": len(files),
            "preview_url": preview_url,
            "created": datetime.now().isoformat()
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                BASEROW_API_URL,
                headers={
                    "Authorization": f"Token {BASEROW_TOKEN}",
                    "Content-Type": "application/json",
                    "Host": BASEROW_HOST
                },
                json=data,
                params={"user_field_names": "true"},
                timeout=10.0
            )
            response.raise_for_status()
            return response.json()
    except Exception as e:
        print(f"Baserow error: {e}")
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
    
    # Generate filename with timestamp_session
    timestamp = create_timestamp()
    session_short = request.session_id.split("_")[-1][:6] if "_" in request.session_id else request.session_id[:6]
    output_file = output_dir / f"{timestamp}_{session_short}.gif"
    
    try:
        from scripts.gifer_api import create_gif_from_files
        
        result = create_gif_from_files(
            input_files=image_files,
            output_path=output_file,
            durations=request.durations,
            quality=request.quality,
            size=request.size
        )
        
        if result["success"]:
            preview_url = f"/preview/{request.session_id}/{output_file.name}"
            return RunResponse(
                success=True,
                filename=output_file.name,
                preview_url=preview_url
            )
        else:
            return RunResponse(success=False, error=result.get("error", "Unknown error"))
            
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
    
    # Generate filename with timestamp_session_NN
    timestamp = create_timestamp()
    session_short = request.session_id.split("_")[-1][:6] if "_" in request.session_id else request.session_id[:6]
    output_file = output_dir / f"{timestamp}_{session_short}_{slide_num:02d}.png"
    
    try:
        from scripts.typer_api import create_text_frame
        
        result = create_text_frame(
            text=request.text,
            output_path=output_file,
            size=request.size,
            template=request.template,
            font=request.font,
            fontsize=request.fontsize,
            layout=request.layout
        )
        
        if result["success"]:
            preview_url = f"/preview/{request.session_id}/{output_file.name}"
            return RunResponse(
                success=True,
                filename=output_file.name,
                preview_url=preview_url,
                slide_number=slide_num
            )
        else:
            return RunResponse(success=False, error=result.get("error", "Unknown error"))
            
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
    
    # Generate filename with timestamp_session
    timestamp = create_timestamp()
    session_short = request.session_id.split("_")[-1][:6] if "_" in request.session_id else request.session_id[:6]
    output_file = output_dir / f"{timestamp}_{session_short}.mp4"
    
    try:
        from scripts.clipper_api import create_clip_from_files
        
        result = create_clip_from_files(
            input_files=media_files,
            output_path=output_file,
            resolution=request.resolution,
            durations=request.durations,
            animation=request.animation,
            direction=request.direction,
            intensity=request.intensity,
            transition=request.transition
        )
        
        if result["success"]:
            preview_url = f"/preview/{request.session_id}/{output_file.name}"
            return RunResponse(
                success=True,
                filename=output_file.name,
                preview_url=preview_url
            )
        else:
            return RunResponse(success=False, error=result.get("error", "Unknown error"))
            
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
        
        # Create filename and folder
        timestamp = create_timestamp()
        folder_name = f"{timestamp}_{request.source}_{request.image_id}"
        filename = f"{timestamp}_{request.source}_{request.image_id}{ext}"
        
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
