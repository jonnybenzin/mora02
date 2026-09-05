"""The media service: sessions, the three renderers, stock photos, finalize.

Split out of main.py in September 2026. This is what the service was named
for -- gifer, clipper and typer over a session's uploads, the stock-photo
search that feeds them, and the finalize step that files the result and tells
Baserow. The rendering itself lives in mora02_core.media; this module is its
HTTP door. Same shape as agents.py, mcp_tools.py, speech.py and steps.py: a
router main.py includes.
"""

from __future__ import annotations

import asyncio
import shutil
import urllib.parse
from functools import partial
from typing import List, Optional

import httpx
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from mora02_core.media import MediaError, create_clip, create_gif, create_text_frame
from runtime import (
    FINAL_DIR, NGINX_BASE_URL, PEXELS_API_KEY, PIXABAY_API_KEY, _media_type,
    container_to_host_path, create_baserow_entry, create_session,
    create_timestamp, get_nginx_url, get_session_dir, inside, safe_segment,
)

router = APIRouter()

# ============================================================================
# MODELS (request and response shapes of the routes below)
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

@router.post("/session/create", response_model=SessionResponse)
async def create_new_session():
    """Create a new session for file uploads"""
    session_id = create_session()
    return SessionResponse(
        session_id=session_id,
        message=f"Session created. Upload files to /upload/{session_id}"
    )

@router.post("/upload/{session_id}")
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

@router.get("/session/{session_id}/files")
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

@router.delete("/session/{session_id}")
async def delete_session(session_id: str):
    """Delete session and all its files"""
    session_dir = get_session_dir(session_id)
    await asyncio.to_thread(shutil.rmtree, session_dir)
    return {"message": f"Session {session_id} deleted"}

# ============================================================================
# ENDPOINTS - GIFER
# ============================================================================

@router.post("/run/gifer", response_model=RunResponse)
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

@router.post("/run/typer", response_model=RunResponse)
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

@router.post("/run/clipper", response_model=RunResponse)
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

@router.get("/preview/{session_id}/{filename}")
async def get_preview(session_id: str, filename: str):
    """Serve preview file from session output"""
    session_dir = get_session_dir(session_id)
    filepath = session_dir / "output" / filename
    
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="File not found")
    
    suffix = filepath.suffix.lower()
    media_type = _media_type(suffix)
    
    return FileResponse(filepath, media_type=media_type)

@router.post("/finalize-session")
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

@router.post("/search/pexels")
async def search_pexels(request: StockSearchRequest):
    """Search Pexels for images"""
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

@router.post("/search/pixabay")
async def search_pixabay(request: StockSearchRequest):
    """Search Pixabay for images"""
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

@router.post("/download/stock")
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
