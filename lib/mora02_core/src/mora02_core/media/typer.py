"""Typer — render multi-line text onto a flat-color background as PNG.

Pure Python via Pillow. Migrated from apps/script-runner/app/scripts/typer_api.py
per ADR-018. Returns an Asset on success, raises MediaError on failure.

Font directory:
    Resolved via env var MORA02_FONTS_DIR (default /app/fonts inside the
    script-runner container). Callers that mount fonts elsewhere can
    override the env var or set ``fonts_dir`` per call.
"""

import json
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont, PngImagePlugin

from mora02_core import auth
from mora02_core.assets import Asset
from mora02_core.media._errors import MediaError


_DEFAULT_FONTS_DIR = Path(auth.get("MORA02_FONTS_DIR", "/app/fonts"))

TEMPLATES = {
    "dark":   ("#e0e0e0", "#2b2b2b"),
    "darker": ("#e0e0e0", "#1b1b1b"),
    "light":  ("#000000", "#e0e0e0"),
    "black":  ("#ffffff", "#000000"),
}

FONTS = {
    "bold":        "JetBrainsMono-ExtraBold.ttf",
    "bold-italic": "JetBrainsMono-ExtraBoldItalic.ttf",
    "thin":        "JetBrainsMono-ExtraLight.ttf",
    "thin-italic": "JetBrainsMono-ExtraLightItalic.ttf",
}


def _parse_size(size_str: str) -> tuple:
    parts = size_str.strip().lower().split("x")
    return (int(parts[0]), int(parts[1]))


def _font_size_px(size_name: str, img_height: int) -> int:
    """Translate small/medium/large into pixel size, or accept a raw int."""
    try:
        return int(size_name)
    except (ValueError, TypeError):
        pass
    name = (size_name or "medium").lower()
    if name == "small":
        return max(20, img_height // 18)
    if name == "large":
        return max(40, img_height // 8)
    # medium
    return max(28, img_height // 12)


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int, draw: ImageDraw.ImageDraw) -> list:
    """Wrap lines to fit max_width, preserving explicit newlines."""
    out_lines: list = []
    for raw_line in text.split("\n"):
        words = raw_line.split(" ")
        current = ""
        for w in words:
            candidate = (current + " " + w).strip() if current else w
            bbox = draw.textbbox((0, 0), candidate, font=font)
            if bbox[2] - bbox[0] <= max_width:
                current = candidate
            else:
                if current:
                    out_lines.append(current)
                current = w
        if current:
            out_lines.append(current)
    return out_lines


def create_text_frame(
    text: str,
    output_path: Path,
    size: str = "1080x1080",
    template: str = "dark",
    font: str = "bold",
    fontsize: str = "medium",
    layout: str = "left",
    *,
    fonts_dir: Optional[Path] = None,
    user_id: str = "default",
) -> Asset:
    """Render text onto a flat-color background and save as PNG.

    Args:
        text: text to render; ``\\n`` (as two chars) is converted to a newline.
        output_path: where to save the PNG.
        size: image dimensions like "1080x1080".
        template: color preset — "dark", "darker", "light", "black".
        font: font preset — "bold", "bold-italic", "thin", "thin-italic".
        fontsize: "small", "medium", "large", or a pixel value as string.
        layout: text alignment — "left" or "centered".
        fonts_dir: optional override for the directory holding the font files.
        user_id: multi-user preparation (E7), default "default".

    Returns:
        Asset of type "image" pointing at the output PNG.

    Raises:
        MediaError: when the chosen font is missing or rendering fails.
    """
    width, height = _parse_size(size)

    if template not in TEMPLATES:
        template = "dark"
    text_color, bg_color = TEMPLATES[template]

    if font not in FONTS:
        font = "bold"

    fonts_root = fonts_dir if fonts_dir is not None else _DEFAULT_FONTS_DIR
    font_path = fonts_root / FONTS[font]
    if not font_path.exists():
        raise MediaError(f"Font not found: {font_path}")

    try:
        font_px = _font_size_px(fontsize, height)
        pil_font = ImageFont.truetype(str(font_path), font_px)

        img = Image.new("RGB", (width, height), bg_color)
        draw = ImageDraw.Draw(img)

        normalized = text.replace("\\n", "\n")

        max_text_width = int(width * (0.9 if layout == "centered" else 0.98))
        lines = _wrap_text(normalized, pil_font, max_text_width, draw)

        line_height = font_px * 1.2
        total_height = len(lines) * line_height

        padding_x = int(width * 0.01)
        ascender_offset = int(font_px * 0.25)

        y = (height - total_height) / 2 if layout == "centered" else padding_x - ascender_offset

        for line in lines:
            if layout == "centered":
                bbox = draw.textbbox((0, 0), line, font=pil_font)
                line_width = bbox[2] - bbox[0]
                x = (width - line_width) / 2
            else:
                x = padding_x
            draw.text((x, y), line, font=pil_font, fill=text_color)
            y += line_height

        output_path.parent.mkdir(parents=True, exist_ok=True)
        pnginfo = PngImagePlugin.PngInfo()
        pnginfo.add_text("mora02", json.dumps({
            "tool": "typer",
            "text": normalized[:500],
            "template": template,
            "font": font,
            "fontsize": fontsize,
            "layout": layout,
            "dimensions": f"{width}x{height}",
        }))
        img.save(output_path, "PNG", pnginfo=pnginfo)
    except MediaError:
        raise
    except Exception as e:
        raise MediaError(f"Failed to render text frame: {e}") from e

    return Asset(
        id=output_path.stem,
        type="image",
        path=output_path,
        user_id=user_id,
        metadata={
            "dimensions": f"{width}x{height}",
            "template": template,
            "font": font,
            "lines": len(lines),
            "size_bytes": output_path.stat().st_size,
        },
    )
