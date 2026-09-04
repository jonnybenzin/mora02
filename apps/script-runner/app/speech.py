"""Speech: the TTS endpoints and the Chatterbox container they may need.

Split out of main.py in September 2026. It was the sixth subsystem in that
file and the only one its own section map did not mention — stranded after the
pipeline-cost code, sharing nothing with it but the module. Same shape as
agents.py and mcp_tools.py: a router main.py includes.
"""

from __future__ import annotations

import asyncio
from functools import partial
from typing import Optional

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from mora02_core.media import MediaError
from mora02_core.media import tts as tts_lib
from runtime import _docker_cli

router = APIRouter()

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


@router.get("/tts/voices")
async def tts_voices():
    """List available TTS voices grouped by language."""
    return tts_lib.list_voices()


@router.get("/tts/health")
async def tts_health():
    """Quick health-poll of kokoro and piper backends."""
    return tts_lib.check_backends()


@router.post("/tts/generate")
async def tts_generate(request: TTSGenerateRequest):
    """Generate speech audio from text — engine routing in the library."""
    try:
        # In a thread: tts_lib.generate uses synchronous httpx with a timeout
        # of up to 180 seconds. Awaited on the loop it froze the whole
        # service for the length of a chatterbox render. Its pipeline
        # twin tts.speak already did this (review 3, 2026-09-04).
        asset = await asyncio.to_thread(
            partial(tts_lib.generate,
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
                ))
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


@router.get("/tts/voices/library")
async def tts_voice_library():
    """List voices stored in the Chatterbox voice library."""
    return tts_lib.voice_library_list()


@router.post("/tts/voices/upload")
async def tts_voice_upload(
    file: UploadFile = File(...),
    voice_name: str = Form(...),
    language: str = Form("de"),
):
    """Convert an uploaded audio/video file to WAV and register it as a voice."""
    audio_bytes = await file.read()
    try:
        # In a thread: this shells out to ffmpeg to convert the sample.
        return await asyncio.to_thread(
            partial(tts_lib.voice_library_upload,
                voice_name=voice_name,
                audio_bytes=audio_bytes,
                source_filename=file.filename or "upload",
                language=language,
                ))
    except MediaError as e:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": str(e)},
        )


@router.delete("/tts/voices/delete/{voice_name}")
async def tts_voice_delete(voice_name: str):
    """Delete a voice from the Chatterbox library."""
    try:
        return tts_lib.voice_library_delete(voice_name)
    except MediaError as e:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": str(e)},
        )


@router.get("/tts/chatterbox/status")
async def tts_chatterbox_status():
    """Check if chatterbox-tts container is running and healthy.

    Uses ``docker inspect`` — script-runner has /var/run/docker.sock mounted
    for this and the start/stop endpoints (see compose).
    """
    try:
        result = await _docker_cli(
            "docker", "inspect", "--format", "{{.State.Status}}", "chatterbox-tts",
            timeout=10,
        )
        container_status = result.stdout.strip() if result.returncode == 0 else "not_found"
        healthy = container_status == "running" and await asyncio.to_thread(
            tts_lib.chatterbox_health)
        return {
            "container": container_status,
            "healthy": healthy,
            "running": container_status == "running",
        }
    except Exception as e:
        return {"container": "error", "healthy": False, "running": False, "error": str(e)}


@router.post("/tts/chatterbox/start")
async def tts_chatterbox_start():
    """Start the chatterbox-tts container."""
    try:
        result = await _docker_cli("docker", "start", "chatterbox-tts", timeout=60)
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


@router.post("/tts/chatterbox/stop")
async def tts_chatterbox_stop():
    """Stop the chatterbox-tts container."""
    try:
        result = await _docker_cli("docker", "stop", "chatterbox-tts", timeout=30)
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
