"""TTS-Dispatcher — routes text-to-speech requests across three engines.

Pure Python wrapping httpx calls to the three TTS containers (piper, kokoro,
chatterbox) plus a voice-library helper. Migrated from
apps/knowledge-api/knowledge-api.py per ADR-020.

Engine routing:
    auto       — language=="de" → piper, else kokoro
    piper      — German offline TTS (CPU)
    kokoro     — Multilingual TTS (CPU)
    chatterbox — Voice-cloning TTS (GPU)

Docker container control for chatterbox (status check via docker inspect,
start/stop) is NOT in this module — it stays in the script-runner service
layer, which holds the docker.sock mount.
"""

import json
import os
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx

from mora02_core import auth
from mora02_core.assets import Asset
from mora02_core.media._errors import MediaError


# ---------------------------------------------------------------------------
# Config — URLs are env-overridable
# ---------------------------------------------------------------------------

KOKORO_URL = auth.get("KOKORO_URL", "http://kokoro-tts:8880")
PIPER_URL = auth.get("PIPER_URL", "http://piper-tts:8107")
CHATTERBOX_URL = auth.get("CHATTERBOX_URL", "http://chatterbox-tts:4123")
TTS_OUTPUT_DIR = Path(auth.get("TTS_OUTPUT_DIR", "/opt/mora02/output/_default/tts"))


# ---------------------------------------------------------------------------
# Voice catalog — kokoro IDs + piper voice mapping
# ---------------------------------------------------------------------------

VOICES = {
    "en": [
        {"id": "af_bella",   "name": "Bella (Female)"},
        {"id": "af_nova",    "name": "Nova (Female)"},
        {"id": "am_adam",    "name": "Adam (Male)"},
        {"id": "am_michael", "name": "Michael (Male)"},
    ],
    "de": [
        {"id": "thorsten",           "name": "Thorsten (Male)",            "model": "de_DE-thorsten-high"},
        {"id": "thorsten_emotional", "name": "Thorsten Emotional (Male)",  "model": "de_DE-thorsten_emotional-medium"},
        {"id": "kerstin",            "name": "Kerstin (Female)",           "model": "de_DE-kerstin-low"},
    ],
}

_PIPER_VOICE_MAP = {v["id"]: v["model"] for v in VOICES["de"]}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def list_voices() -> dict:
    """Return the voice catalog grouped by language."""
    return VOICES


def check_backends() -> dict:
    """Quick health-poll of the kokoro and piper backends.

    Chatterbox status is intentionally not here — it requires docker
    inspection which belongs to the service layer, not the library.
    """
    status = {"kokoro": "unknown", "piper": "unknown"}
    try:
        r = httpx.get(f"{KOKORO_URL}/health", timeout=5.0)
        status["kokoro"] = "ok" if r.status_code == 200 else f"error ({r.status_code})"
    except Exception as e:
        status["kokoro"] = f"error: {str(e)[:100]}"
    try:
        r = httpx.get(f"{PIPER_URL}/health", timeout=5.0)
        status["piper"] = "ok" if r.status_code == 200 else f"error ({r.status_code})"
    except Exception as e:
        status["piper"] = f"error: {str(e)[:100]}"
    return status


def _pick_engine(engine_pref: str, language: str) -> str:
    """Resolve an engine preference into a concrete engine name."""
    if engine_pref == "chatterbox":
        return "chatterbox"
    if engine_pref == "piper":
        return "piper"
    if engine_pref == "auto" and language == "de":
        return "piper"
    return "kokoro"


def _embed_metadata(output_path: Path, meta: dict, voice: str, engine: str) -> None:
    """Best-effort ffmpeg metadata embedding into a WAV or MP3.

    Failures are swallowed — metadata is optional, the audio itself stays.
    """
    fmt = output_path.suffix.lstrip(".")
    if fmt not in ("wav", "mp3"):
        return
    try:
        meta_json = json.dumps(meta)
        tmp = output_path.with_suffix(output_path.suffix + ".tmp")
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(output_path),
                "-metadata", f"comment={meta_json}",
                "-metadata", f"title=TTS: {voice}",
                "-metadata", f"artist=mora02 ({engine})",
                "-c", "copy", str(tmp),
            ],
            capture_output=True,
            check=False,
        )
        if tmp.exists():
            os.replace(tmp, output_path)
    except Exception:
        pass


def generate(
    text: str,
    language: str = "en",
    voice: Optional[str] = None,
    format: str = "wav",
    engine_pref: str = "auto",
    speed: float = 1.0,
    noise_scale: float = 0.667,
    noise_w: float = 0.8,
    exaggeration: float = 0.5,
    cfg_weight: float = 0.5,
    temperature: float = 0.8,
    cb_voice: str = "",
    *,
    user_id: str = "default",
) -> Asset:
    """Synthesize speech audio from text and return an Asset.

    Routes to the matching engine container, saves the result under
    TTS_OUTPUT_DIR with a timestamp-counter filename, embeds metadata.

    Raises:
        MediaError: empty text, backend non-200, or IO failure.
    """
    text = (text or "").strip()
    if not text:
        raise MediaError("No text provided")

    if voice is None:
        voice = "thorsten" if language == "de" else "af_bella"
    engine = _pick_engine(engine_pref, language)

    TTS_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%y%m%d-%H%M")
    existing = sum(1 for f in TTS_OUTPUT_DIR.iterdir() if f.name.startswith(f"vox_{timestamp}_"))
    counter = existing + 1
    filename = f"vox_{timestamp}_{counter:03d}.{format}"
    output_path = TTS_OUTPUT_DIR / filename

    try:
        if engine == "chatterbox":
            payload = {
                "input": text,
                "voice": cb_voice if cb_voice else "alloy",
                "exaggeration": exaggeration,
                "cfg_weight": cfg_weight,
                "temperature": temperature,
            }
            r = httpx.post(f"{CHATTERBOX_URL}/v1/audio/speech", json=payload, timeout=180.0)
        elif engine == "piper":
            model_name = _PIPER_VOICE_MAP.get(voice, voice)
            payload = {
                "input": text, "voice": model_name, "response_format": format,
                "speed": speed, "noise_scale": noise_scale, "noise_w": noise_w,
            }
            r = httpx.post(f"{PIPER_URL}/v1/audio/speech", json=payload, timeout=120.0)
        else:  # kokoro
            payload = {
                "input": text, "voice": voice, "response_format": format,
                "speed": speed,
            }
            r = httpx.post(f"{KOKORO_URL}/v1/audio/speech", json=payload, timeout=120.0)
    except httpx.TimeoutException as e:
        raise MediaError(f"{engine} backend timed out") from e
    except Exception as e:
        raise MediaError(f"{engine} backend call failed: {e}") from e

    if r.status_code != 200:
        raise MediaError(f"{engine} returned {r.status_code}: {r.text[:200]}")

    output_path.write_bytes(r.content)

    _embed_metadata(
        output_path,
        meta={
            "engine": engine, "voice": voice, "language": language,
            "speed": speed, "text": text[:500],
            "format": format, "timestamp": timestamp,
        },
        voice=voice,
        engine=engine,
    )

    return Asset(
        id=output_path.stem,
        type="audio",
        path=output_path,
        user_id=user_id,
        metadata={
            "url": f"/tool-assets/tts/{filename}",
            "filename": filename,
            "voice": voice,
            "engine": engine,
            "language": language,
            "text_length": len(text),
        },
    )


# ---------------------------------------------------------------------------
# Chatterbox voice library — file-upload pipeline
# ---------------------------------------------------------------------------


def voice_library_list() -> dict:
    """List the voices stored in the Chatterbox voice library."""
    try:
        r = httpx.get(f"{CHATTERBOX_URL}/voices", timeout=10.0)
        if r.status_code == 200:
            data = r.json()
            return {"voices": data.get("voices", []), "count": data.get("count", 0)}
        return {"voices": [], "count": 0}
    except Exception:
        return {"voices": [], "count": 0}


def voice_library_upload(voice_name: str, audio_bytes: bytes, source_filename: str, language: str = "de") -> dict:
    """Convert an uploaded audio/video file to WAV and register it as a voice.

    Uses ffmpeg to extract audio in the format Chatterbox expects
    (mono, 22kHz, 16-bit PCM). The temporary files are cleaned up
    even on errors.

    Raises:
        MediaError: invalid input, ffmpeg failure, or Chatterbox rejection.
    """
    voice_name = (voice_name or "").strip()
    if not voice_name:
        raise MediaError("voice_name is required")
    if not audio_bytes:
        raise MediaError("empty audio payload")

    suffix = Path(source_filename).suffix or ".tmp"

    tmp_in = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp_in_path = Path(tmp_in.name)
    tmp_out_path = tmp_in_path.with_suffix(tmp_in_path.suffix + ".wav")

    try:
        tmp_in.write(audio_bytes)
        tmp_in.close()

        result = subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(tmp_in_path),
                "-vn",
                "-acodec", "pcm_s16le",
                "-ar", "22050",
                "-ac", "1",
                str(tmp_out_path),
            ],
            capture_output=True, text=True, timeout=60, check=False,
        )
        if result.returncode != 0:
            raise MediaError(f"ffmpeg conversion failed: {result.stderr[:300]}")

        with open(tmp_out_path, "rb") as wav_file:
            r = httpx.post(
                f"{CHATTERBOX_URL}/voices",
                files={"voice_file": (f"{voice_name}.wav", wav_file, "audio/wav")},
                data={"voice_name": voice_name, "language": language},
                timeout=30.0,
            )

        if r.status_code in (200, 201):
            return {
                "success": True,
                "message": f"Voice '{voice_name}' uploaded successfully",
                "voice_name": voice_name,
                "language": language,
            }
        raise MediaError(f"Chatterbox rejected upload: {r.text[:300]}")
    finally:
        for p in (tmp_in_path, tmp_out_path):
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass


def voice_library_delete(voice_name: str) -> dict:
    """Delete a voice from the Chatterbox library."""
    try:
        r = httpx.delete(f"{CHATTERBOX_URL}/voices/{voice_name}", timeout=10.0)
        if r.status_code == 200:
            return {"success": True, "message": f"Voice '{voice_name}' deleted"}
        raise MediaError(f"chatterbox delete returned {r.status_code}: {r.text[:300]}")
    except MediaError:
        raise
    except Exception as e:
        raise MediaError(f"chatterbox delete failed: {e}") from e


def chatterbox_health() -> bool:
    """Best-effort: is Chatterbox responding to /health?"""
    try:
        r = httpx.get(f"{CHATTERBOX_URL}/health", timeout=5.0)
        return r.status_code == 200
    except Exception:
        return False
