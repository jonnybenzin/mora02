"""Gifer — animated GIF builder from a list of image files.

Pure Python via Pillow. Migrated from apps/script-runner/app/scripts/gifer_api.py
per ADR-018. Returns an Asset on success, raises MediaError on failure.
"""

import json
from pathlib import Path
from typing import List, Optional

from PIL import Image, ImageOps

from mora02_core.assets import Asset
from mora02_core.media._errors import MediaError


QUALITY_PRESETS = {
    "low":    {"colors": 64,  "optimize": True},
    "medium": {"colors": 128, "optimize": True},
    "high":   {"colors": 256, "optimize": True},
    "ultra":  {"colors": 256, "optimize": False},
}

_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")


def _parse_size(size_str: Optional[str]) -> Optional[tuple]:
    if not size_str:
        return None
    s = size_str.strip().lower()
    if "x" in s:
        parts = s.split("x")
        return (int(parts[0]), int(parts[1]))
    return (int(s), None)


def _parse_durations(durations_str: str, num_frames: int) -> List[int]:
    """Parse '1,2,2,4' seconds → [1000,2000,2000,4000] milliseconds, padded/trimmed to num_frames."""
    parts = [p.strip() for p in durations_str.replace(" ", ",").split(",") if p.strip()]
    durations_sec: List[float] = []
    for p in parts:
        try:
            durations_sec.append(float(p))
        except ValueError:
            durations_sec.append(1.0)

    if len(durations_sec) == 1:
        durations_sec = durations_sec * num_frames
    elif len(durations_sec) < num_frames:
        last = durations_sec[-1] if durations_sec else 1.0
        durations_sec.extend([last] * (num_frames - len(durations_sec)))
    else:
        durations_sec = durations_sec[:num_frames]

    return [int(d * 1000) for d in durations_sec]


def _target_dimensions(images: List[Path], user_size: Optional[tuple]) -> tuple:
    if not images:
        return (800, 600)
    ref_img = Image.open(images[0])
    original_ratio = ref_img.width / ref_img.height

    if user_size:
        width, height = user_size
        if height is None:
            height = int(width / original_ratio)
        return (width, height)

    min_area = float("inf")
    target = (ref_img.width, ref_img.height)
    for img_path in images:
        img = Image.open(img_path)
        area = img.width * img.height
        if area < min_area:
            min_area = area
            target = (img.width, img.height)
    return target


def _standardize(img: Image.Image, width: int, height: int) -> Image.Image:
    return ImageOps.fit(img, (width, height), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))


def create_gif(
    input_files: List[Path],
    output_path: Path,
    durations: str,
    quality: str = "medium",
    size: Optional[str] = None,
    *,
    user_id: str = "default",
) -> Asset:
    """Create an animated GIF from a list of image files.

    Args:
        input_files: paths to source images (sorted alphabetically before encoding).
        output_path: where to save the GIF.
        durations: comma-separated seconds per frame, e.g. "1,2,2,4".
        quality: one of "low" / "medium" / "high" / "ultra".
        size: target dimensions like "800x600" or "800" (width-only, height computed).
        user_id: multi-user preparation (E7), default "default".

    Returns:
        Asset of type "image" pointing at the output GIF, with metadata
        (frames, dimensions, duration_seconds, size_bytes).

    Raises:
        MediaError: when no valid image files exist or saving fails.
    """
    images = sorted(f for f in input_files if f.suffix.lower() in _IMAGE_EXTENSIONS)
    if not images:
        raise MediaError("No valid image files found")

    user_size = _parse_size(size)
    duration_list = _parse_durations(durations, len(images))
    preset = QUALITY_PRESETS.get(quality, QUALITY_PRESETS["medium"])

    target_width, target_height = _target_dimensions(images, user_size)

    frames: List[Image.Image] = []
    for img_path in images:
        img = Image.open(img_path)
        img = _standardize(img, target_width, target_height)
        if img.mode != "RGB":
            img = img.convert("RGB")
        if preset["colors"] < 256:
            img = img.convert("P", palette=Image.Palette.ADAPTIVE, colors=preset["colors"])
            img = img.convert("RGB")
        frames.append(img)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    gif_comment = json.dumps({
        "tool": "gifer",
        "quality": quality,
        "frames": len(frames),
        "durations_ms": duration_list,
        "dimensions": f"{target_width}x{target_height}",
        "source_files": [f.name for f in input_files],
    })

    try:
        frames[0].save(
            output_path,
            save_all=True,
            append_images=frames[1:],
            duration=duration_list,
            loop=0,
            optimize=preset["optimize"],
            comment=gif_comment.encode("utf-8"),
        )
    except Exception as e:
        raise MediaError(f"Failed to save GIF: {e}") from e

    total_duration_s = sum(duration_list) / 1000.0
    return Asset(
        id=output_path.stem,
        type="image",
        path=output_path,
        user_id=user_id,
        metadata={
            "frames": len(frames),
            "dimensions": f"{target_width}x{target_height}",
            "duration_seconds": round(total_duration_s, 2),
            "size_bytes": output_path.stat().st_size,
            "quality": quality,
        },
    )
