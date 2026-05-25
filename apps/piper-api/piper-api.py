#!/usr/bin/env python3
"""
Mora02 Piper TTS HTTP Wrapper
OpenAI-compatible API around Piper CLI for German text-to-speech.
"""

import os
import subprocess
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

app = FastAPI(title="Piper TTS API", version="1.0.0")

MODELS_DIR = Path(os.getenv("PIPER_MODELS_DIR", "/models"))
PIPER_BIN = os.getenv("PIPER_BIN", "/usr/local/piper/piper")


class SpeechRequest(BaseModel):
    input: str
    voice: str = "de_DE-thorsten-high"
    response_format: str = "wav"
    speed: float = 1.0           # 0.5 (slow) - 2.0 (fast)
    noise_scale: float = 0.667   # 0.0 (monotone) - 1.0 (expressive)
    noise_w: float = 0.8         # phoneme width variation (timbre)


@app.get("/health")
def health():
    voices = _list_voices()
    return {"status": "ok", "voices_loaded": len(voices)}


@app.get("/v1/voices")
def list_voices():
    """List available .onnx voice models."""
    voices = _list_voices()
    return {"voices": voices}


@app.post("/v1/audio/speech")
def synthesize(req: SpeechRequest):
    """Generate speech audio from text. OpenAI-compatible endpoint."""
    if not req.input.strip():
        raise HTTPException(status_code=400, detail="No input text provided")

    voice_name = req.voice
    # Allow short names: "thorsten" -> "de_DE-thorsten-high"
    model_path = _resolve_voice(voice_name)
    if not model_path:
        available = [v["id"] for v in _list_voices()]
        raise HTTPException(
            status_code=400,
            detail=f"Voice '{voice_name}' not found. Available: {available}",
        )

    suffix = ".wav"  # Piper always outputs WAV
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        out_path = tmp.name

    try:
        # Convert speed to length_scale (inverse: speed 2.0 = length_scale 0.5)
        length_scale = max(0.25, min(4.0, 1.0 / req.speed)) if req.speed > 0 else 1.0
        noise_scale = max(0.0, min(1.0, req.noise_scale))
        noise_w = max(0.0, min(1.0, req.noise_w))

        result = subprocess.run(
            [
                PIPER_BIN,
                "--model", str(model_path),
                "--output_file", out_path,
                "--length-scale", str(length_scale),
                "--noise-scale", str(noise_scale),
                "--noise-w", str(noise_w),
            ],
            input=req.input,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            raise HTTPException(
                status_code=500,
                detail=f"Piper failed: {result.stderr[:500]}",
            )

        if not os.path.exists(out_path) or os.path.getsize(out_path) < 100:
            raise HTTPException(status_code=500, detail="Piper produced no output")

        return FileResponse(
            out_path,
            media_type="audio/wav",
            filename=f"{voice_name}.wav",
            background=None,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Piper timed out")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _list_voices():
    """Scan MODELS_DIR for .onnx files."""
    if not MODELS_DIR.exists():
        return []
    voices = []
    for f in sorted(MODELS_DIR.glob("*.onnx")):
        voice_id = f.stem  # e.g. "de_DE-thorsten-high"
        voices.append({"id": voice_id, "file": f.name})
    return voices


def _resolve_voice(name: str):
    """Resolve a voice name to an .onnx file path.

    Accepts full name ("de_DE-thorsten-high") or short name ("thorsten").
    """
    # Exact match first
    exact = MODELS_DIR / f"{name}.onnx"
    if exact.exists():
        return exact

    # Partial match: find first model containing the short name
    for f in MODELS_DIR.glob("*.onnx"):
        if name in f.stem:
            return f

    return None
