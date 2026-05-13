#!/usr/bin/env python3
"""
Typer API Module - Wrapper for typer script functionality
For use with Script Runner FastAPI service
"""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, PngImagePlugin
from typing import Dict, Any

# Font directory inside container
FONT_DIR = Path("/app/fonts")

# Templates: (text_color, bg_color)
TEMPLATES = {
    "dark":   ("#e0e0e0", "#2b2b2b"),
    "darker": ("#e0e0e0", "#1b1b1b"),
    "light":  ("#000000", "#e0e0e0"),
    "black":  ("#ffffff", "#000000"),
}

# Font mapping
FONTS = {
    "bold":        "JetBrainsMono-ExtraBold.ttf",
    "bold-italic": "JetBrainsMono-ExtraBoldItalic.ttf",
    "thin":        "JetBrainsMono-ExtraLight.ttf",
    "thin-italic": "JetBrainsMono-ExtraLightItalic.ttf",
}

def parse_size(size_str: str) -> tuple:
    """Parse '1080x1080' to (width, height)"""
    parts = size_str.lower().split('x')
    return int(parts[0]), int(parts[1])

def get_font_size(size_name: str, img_height: int) -> int:
    """Calculate font size relative to image height"""
    ratios = {
        "small": 0.06,
        "medium": 0.09,
        "large": 0.12,
    }
    if size_name in ratios:
        return int(img_height * ratios[size_name])
    # Direct pixel value
    try:
        return int(size_name)
    except ValueError:
        return int(img_height * 0.09)  # default to medium

def wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int, draw: ImageDraw.Draw) -> list:
    """Wrap text to fit within max_width"""
    lines = []
    for paragraph in text.split('\n'):
        if not paragraph:
            lines.append("")
            continue
        
        words = paragraph.split(' ')
        current_line = ""
        
        for word in words:
            test_line = f"{current_line} {word}".strip()
            bbox = draw.textbbox((0, 0), test_line, font=font)
            if bbox[2] <= max_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word
        
        if current_line:
            lines.append(current_line)
    
    return lines

def create_text_frame(
    text: str,
    output_path: Path,
    size: str = "1080x1080",
    template: str = "dark",
    font: str = "bold",
    fontsize: str = "medium",
    layout: str = "left"
) -> Dict[str, Any]:
    """
    Create text frame PNG
    
    Args:
        text: Text to render (use \\n for line breaks)
        output_path: Where to save the PNG
        size: Image dimensions like "1080x1080"
        template: Color template (dark, darker, light, black)
        font: Font style (bold, bold-italic, thin, thin-italic)
        fontsize: Size (small, medium, large, or pixel value)
        layout: Text alignment (left, centered)
    
    Returns:
        Dict with success status, error message if failed
    """
    try:
        # Parse parameters
        width, height = parse_size(size)
        
        if template not in TEMPLATES:
            template = "dark"
        text_color, bg_color = TEMPLATES[template]
        
        if font not in FONTS:
            font = "bold"
        
        # Load font
        font_path = FONT_DIR / FONTS[font]
        if not font_path.exists():
            return {"success": False, "error": f"Font not found: {font_path}"}
        
        font_px = get_font_size(fontsize, height)
        pil_font = ImageFont.truetype(str(font_path), font_px)
        
        # Create image
        img = Image.new('RGB', (width, height), bg_color)
        draw = ImageDraw.Draw(img)
        
        # Process text (convert \n to actual line breaks)
        text = text.replace('\\n', '\n')
        
        # Wrap text
        if layout == "centered":
            max_text_width = int(width * 0.9)
        else:
            max_text_width = int(width * 0.98)
        
        lines = wrap_text(text, pil_font, max_text_width, draw)
        
        # Calculate line height and positions
        line_height = font_px * 1.2
        total_height = len(lines) * line_height
        
        padding_x = int(width * 0.01)
        ascender_offset = int(font_px * 0.25)
        
        # Start Y position
        if layout == "centered":
            y = (height - total_height) / 2
        else:  # left
            y = padding_x - ascender_offset
        
        # Draw text
        for line in lines:
            if layout == "centered":
                bbox = draw.textbbox((0, 0), line, font=pil_font)
                line_width = bbox[2] - bbox[0]
                x = (width - line_width) / 2
            else:  # left
                x = padding_x
            
            draw.text((x, y), line, font=pil_font, fill=text_color)
            y += line_height
        
        # Save with metadata
        output_path.parent.mkdir(parents=True, exist_ok=True)
        import json as _json
        pnginfo = PngImagePlugin.PngInfo()
        pnginfo.add_text("mora02", _json.dumps({
            "tool": "typer", "text": text[:500], "template": template,
            "font": font, "fontsize": fontsize, "layout": layout,
            "dimensions": f"{width}x{height}",
        }))
        img.save(output_path, 'PNG', pnginfo=pnginfo)
        
        return {
            "success": True,
            "filename": output_path.name,
            "dimensions": f"{width}x{height}",
            "template": template,
            "font": font,
            "lines": len(lines)
        }
        
    except Exception as e:
        return {"success": False, "error": str(e)}
