"""Clipper — concatenate images and video snippets into one MP4.

Each image becomes a Ken-Burns-style clip (pan/zoom) with silent audio;
each video keeps its own audio or gets a silent track stitched in.
Pure Python wrapping ffmpeg via subprocess. Migrated from
apps/script-runner/app/scripts/clipper_api.py per ADR-018.
"""

import json
import math
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List

from mora02_core.assets import Asset
from mora02_core.media._errors import MediaError


RESOLUTION_PRESETS = {
    "1080p":  (1920, 1080),
    "720p":   (1280, 720),
    "4k":     (3840, 2160),
    "square": (1080, 1080),
    "story":  (1080, 1920),
    "reels":  (1080, 1920),
}

_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
_VIDEO_EXTENSIONS = (".mp4", ".mov", ".webm", ".avi", ".mkv")

_DEFAULT_FPS = 30
_CRF_QUALITY = 18
_FFMPEG_PRESET = "medium"


def _parse_resolution(resolution_str: str) -> tuple:
    s = resolution_str.strip().lower()
    if s in RESOLUTION_PRESETS:
        return RESOLUTION_PRESETS[s]
    match = re.match(r"^(\d+)\s*[xX×]\s*(\d+)$", s)
    if match:
        return (int(match.group(1)), int(match.group(2)))
    if s.isdigit():
        width = int(s)
        return (width, int(width * 9 / 16))
    return (1920, 1080)


def _parse_array(input_str: str, count: int, default: float) -> List[float]:
    parts = [p.strip() for p in input_str.replace(" ", ",").split(",") if p.strip()]
    values: List[float] = []
    for p in parts:
        try:
            values.append(float(p))
        except ValueError:
            values.append(default)
    if not values:
        return [default] * count
    if len(values) == 1:
        return values * count
    while len(values) < count:
        values.append(values[-1])
    return values[:count]


def _direction_to_vector(degrees: float, intensity: float) -> tuple:
    radians = math.radians(degrees - 90)
    return math.cos(radians) * intensity, math.sin(radians) * intensity


def _aspect_crop(width: int, height: int) -> str:
    """ffmpeg filter snippet: crop to cover/fill the target aspect ratio."""
    return (
        f"crop="
        f"if(gt(iw/ih\\,{width}/{height})\\,ih*{width}/{height}\\,iw):"
        f"if(gt(iw/ih\\,{width}/{height})\\,ih\\,iw*{height}/{width})"
    )


def _animation_filter(anim_type: str, direction: float, intensity: float,
                      duration: float, width: int, height: int, fps: int) -> str:
    frames = max(int(duration * fps), 2)
    if anim_type == "none":
        return f"{_aspect_crop(width, height)},scale={width}:{height}"

    dx, dy = _direction_to_vector(direction, intensity)
    ease = f"((on/{frames})*(on/{frames})*(3-2*(on/{frames})))"

    if anim_type == "pan":
        zoom = 1.0 + (intensity / 100) * 0.5
        start_x = 0.5 - (dx / 200)
        start_y = 0.5 - (dy / 200)
        delta_x = dx / 100
        delta_y = dy / 100
        x_expr = f"iw*({start_x}+{delta_x}*{ease})-iw/2/{zoom}"
        y_expr = f"ih*({start_y}+{delta_y}*{ease})-ih/2/{zoom}"
        ac = _aspect_crop(width, height)
        return f"{ac},zoompan=z={zoom}:x='{x_expr}':y='{y_expr}':d={frames}:s={width}x{height}:fps={fps}"

    if anim_type in ("zoom_in", "zoom_out"):
        focus_x = max(0.2, min(0.8, 0.5 + (dx / 200)))
        focus_y = max(0.2, min(0.8, 0.5 + (dy / 200)))
        zoom_amount = 1 + (intensity / 100)
        if anim_type == "zoom_in":
            z_expr = f"1+({zoom_amount}-1)*{ease}"
        else:
            z_expr = f"{zoom_amount}-({zoom_amount}-1)*{ease}"
        x_expr = f"iw*{focus_x}-(iw/zoom/2)"
        y_expr = f"ih*{focus_y}-(ih/zoom/2)"
        ac = _aspect_crop(width, height)
        return f"{ac},zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}':d={frames}:s={width}x{height}:fps={fps}"

    return f"{_aspect_crop(width, height)},scale={width}:{height}"


def _get_video_duration(video_path: Path) -> float:
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
           "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return float(result.stdout.strip())
    except (ValueError, TypeError):
        return 0.0


def _video_has_audio(video_path: Path) -> bool:
    cmd = ["ffprobe", "-v", "error", "-select_streams", "a",
           "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(video_path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return bool(result.stdout.strip())


def mux_audio(video_path, audio_path, out_path) -> Path:
    """Lay an audio track over a video as its soundtrack (replacing existing audio).

    Cut to the shorter of the two (``-shortest``) so the clip length drives. Video is
    stream-copied (no re-encode); audio is encoded to AAC. Backs the ``soundtrack``
    param of the clip.generate op.
    """
    out_path = Path(out_path)
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path), "-i", str(audio_path),
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac",
        "-b:a", "192k", "-shortest", str(out_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not out_path.is_file():
        raise MediaError(f"audio mux failed: {proc.stderr[-300:]}")
    return out_path


def create_clip(
    input_files: List[Path],
    output_path: Path,
    resolution: str = "1080p",
    durations: str = "4",
    animation: str = "pan",
    direction: str = "90",
    intensity: str = "20",
    transition: str = "1",
    *,
    user_id: str = "default",
) -> Asset:
    """Assemble an MP4 from images (Ken-Burns) and video snippets.

    Args:
        input_files: paths to images and/or videos, sorted alphabetically.
        output_path: where to save the final MP4.
        resolution: preset name ("1080p", "720p", "4k", "square", "story", "reels")
            or "WIDTHxHEIGHT" or just a width.
        durations: per-image clip length in seconds, comma-separated.
        animation: "pan" / "zoom_in" / "zoom_out" / "none".
        direction: pan direction in degrees, comma-separated per image.
        intensity: pan/zoom intensity 0-100, comma-separated per image.
        transition: kept for API symmetry, not yet wired to a filter.
        user_id: multi-user preparation (E7), default "default".

    Returns:
        Asset of type "video" pointing at the final MP4.

    Raises:
        MediaError: when no valid media files exist or ffmpeg fails.
    """
    width, height = _parse_resolution(resolution)
    fps = _DEFAULT_FPS

    media = []
    for f in sorted(input_files, key=lambda x: x.name):
        ext = f.suffix.lower()
        if ext in _IMAGE_EXTENSIONS:
            media.append({"path": f, "type": "image"})
        elif ext in _VIDEO_EXTENSIONS:
            media.append({"path": f, "type": "video"})

    if not media:
        raise MediaError("No valid media files found")

    image_count = sum(1 for m in media if m["type"] == "image")
    duration_list = _parse_array(durations, image_count, 4.0)
    direction_list = _parse_array(direction, image_count, 90)
    intensity_list = _parse_array(intensity, image_count, 20)

    temp_dir = Path(tempfile.mkdtemp(prefix="clipper_"))

    try:
        clip_paths: List[Path] = []
        duration_idx = 0

        for idx, m in enumerate(media):
            clip_path = temp_dir / f"clip_{idx:03d}.mp4"

            if m["type"] == "image":
                dur = duration_list[duration_idx] if duration_idx < len(duration_list) else 4.0
                dir_val = direction_list[duration_idx] if duration_idx < len(direction_list) else 90
                int_val = intensity_list[duration_idx] if duration_idx < len(intensity_list) else 20
                duration_idx += 1

                filter_str = _animation_filter(animation, dir_val, int_val, dur, width, height, fps)
                cmd = [
                    "ffmpeg", "-y",
                    "-loop", "1",
                    "-i", str(m["path"]),
                    "-f", "lavfi",
                    "-i", "anullsrc=r=44100:cl=stereo",
                    "-vf", filter_str,
                    "-t", str(dur),
                    "-c:v", "libx264",
                    "-preset", _FFMPEG_PRESET,
                    "-crf", str(_CRF_QUALITY),
                    "-c:a", "aac",
                    "-b:a", "128k",
                    "-pix_fmt", "yuv420p",
                    "-shortest",
                    str(clip_path),
                ]
                subprocess.run(cmd, capture_output=True, text=True)

            else:
                has_audio = _video_has_audio(m["path"])
                if has_audio:
                    cmd = [
                        "ffmpeg", "-y",
                        "-i", str(m["path"]),
                        "-vf", f"{_aspect_crop(width, height)},scale={width}:{height}",
                        "-c:v", "libx264",
                        "-preset", _FFMPEG_PRESET,
                        "-crf", str(_CRF_QUALITY),
                        "-r", str(fps),
                        "-c:a", "aac",
                        "-b:a", "128k",
                        "-pix_fmt", "yuv420p",
                        str(clip_path),
                    ]
                else:
                    cmd = [
                        "ffmpeg", "-y",
                        "-i", str(m["path"]),
                        "-f", "lavfi",
                        "-i", "anullsrc=r=44100:cl=stereo",
                        "-vf", f"{_aspect_crop(width, height)},scale={width}:{height}",
                        "-c:v", "libx264",
                        "-preset", _FFMPEG_PRESET,
                        "-crf", str(_CRF_QUALITY),
                        "-r", str(fps),
                        "-c:a", "aac",
                        "-b:a", "128k",
                        "-map", "0:v",
                        "-map", "1:a",
                        "-shortest",
                        "-pix_fmt", "yuv420p",
                        str(clip_path),
                    ]
                subprocess.run(cmd, capture_output=True, text=True)

            if clip_path.exists():
                clip_paths.append(clip_path)

        if not clip_paths:
            raise MediaError("Failed to create any clips")

        output_path.parent.mkdir(parents=True, exist_ok=True)

        if len(clip_paths) == 1:
            shutil.copy2(clip_paths[0], output_path)
        else:
            concat_file = temp_dir / "concat.txt"
            with open(concat_file, "w") as f:
                for clip in clip_paths:
                    f.write(f"file '{clip}'\n")

            clip_meta = json.dumps({
                "tool": "clipper",
                "resolution": resolution,
                "animation": animation,
                "direction": direction,
                "intensity": intensity,
                "transition": transition,
                "clips": len(clip_paths),
                "source_files": [f.name for f in input_files],
            })
            cmd = [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_file),
                "-c:v", "libx264",
                "-preset", _FFMPEG_PRESET,
                "-crf", str(_CRF_QUALITY),
                "-c:a", "aac",
                "-b:a", "128k",
                "-metadata", f"comment={clip_meta}",
                "-metadata", "artist=mora02 (clipper)",
                str(output_path),
            ]
            subprocess.run(cmd, capture_output=True, text=True)

        if not output_path.exists():
            raise MediaError("Failed to create final video")

        final_duration = _get_video_duration(output_path)
        final_has_audio = _video_has_audio(output_path)

        return Asset(
            id=output_path.stem,
            type="video",
            path=output_path,
            user_id=user_id,
            metadata={
                "clips": len(clip_paths),
                "dimensions": f"{width}x{height}",
                "duration_seconds": round(final_duration, 2),
                "size_bytes": output_path.stat().st_size,
                "has_audio": final_has_audio,
            },
        )

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
