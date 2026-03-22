#!/usr/bin/env python3
"""
typer - Text-Frame Generator für gifer
Erzeugt PNG-Bilder mit Text in JetBrains Mono
"""

import argparse
import os
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

# Pfade
FONT_DIR = "/opt/mora02/output/_default/typer/fonts"
OUTPUT_DIR = "/opt/mora02/output/_default/typer"

# Templates: text_color, bg_color
TEMPLATES = {
    "dark":   ("#e0e0e0", "#2b2b2b"),
    "darker": ("#e0e0e0", "#1b1b1b"),
    "light":  ("#000000", "#e0e0e0"),
    "black":  ("#ffffff", "#000000"),
}

# Font-Mapping
FONTS = {
    "bold":        "JetBrainsMono-ExtraBold.ttf",
    "bold-italic": "JetBrainsMono-ExtraBoldItalic.ttf",
    "thin":        "JetBrainsMono-ExtraLight.ttf",
    "thin-italic": "JetBrainsMono-ExtraLightItalic.ttf",
}

def parse_size(size_str):
    """Parse '1080x1080' to (width, height)"""
    parts = size_str.lower().split('x')
    return int(parts[0]), int(parts[1])

def get_font_size(size_name, img_height):
    """Berechne Schriftgröße relativ zur Bildhöhe"""
    ratios = {
        "small": 0.06,
        "medium": 0.09,
        "large": 0.12,
    }
    if size_name in ratios:
        return int(img_height * ratios[size_name])
    return int(size_name)  # Direkte Pixelangabe

def wrap_text(text, font, max_width, draw):
    """Umbreche Text wenn nötig"""
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

def create_text_frame(text, size, template, font_name, fontsize, layout):
    """Erstelle Text-Frame PNG"""
    
    width, height = parse_size(size)
    text_color, bg_color = TEMPLATES[template]
    
    # Font laden
    font_path = os.path.join(FONT_DIR, FONTS[font_name])
    font_px = get_font_size(fontsize, height)
    font = ImageFont.truetype(font_path, font_px)
    
    # Bild erstellen
    img = Image.new('RGB', (width, height), bg_color)
    draw = ImageDraw.Draw(img)
    
    # Text umbrechen (95% der Bildbreite für left, 90% für centered)
    if layout == "centered":
        max_text_width = int(width * 0.9)
    else:
        max_text_width = int(width * 0.98)
    
    lines = wrap_text(text, font, max_text_width, draw)
    
    # Zeilenhöhe
    line_height = font_px * 1.2
    total_height = len(lines) * line_height
    
    # Padding für left-Layout
    padding_x = int(width * 0.01)
    
    # Font-Ascender kompensieren (negativer Offset nach oben)
    ascender_offset = int(font_px * 0.25)
    
    # Startposition Y
    if layout == "centered":
        y = (height - total_height) / 2
    else:  # left
        y = padding_x - ascender_offset
    
    # Text zeichnen
    for line in lines:
        if layout == "centered":
            bbox = draw.textbbox((0, 0), line, font=font)
            line_width = bbox[2] - bbox[0]
            x = (width - line_width) / 2
        else:  # left
            x = padding_x
        
        draw.text((x, y), line, font=font, fill=text_color)
        y += line_height
    
    # Dateiname mit Timestamp
    timestamp = datetime.now().strftime("%y%m%d%H%M")
    
    # Nächste freie Nummer finden
    existing = [f for f in os.listdir(OUTPUT_DIR) if f.startswith(f"{timestamp}_typer_")]
    num = len(existing) + 1
    
    filename = f"{timestamp}_typer_{num:03d}.png"
    filepath = os.path.join(OUTPUT_DIR, filename)
    
    img.save(filepath, 'PNG')
    print(f"✓ {filepath}")
    
    return filepath

def main():
    parser = argparse.ArgumentParser(description='Text-Frame Generator')
    parser.add_argument('text', help='Text (\\n für Zeilenumbruch)')
    parser.add_argument('--size', default='1080x1080', help='Bildgröße WxH (default: 1080x1080)')
    parser.add_argument('--template', choices=TEMPLATES.keys(), default='dark', help='Farbtemplate')
    parser.add_argument('--font', choices=FONTS.keys(), default='bold', help='Schriftart')
    parser.add_argument('--fontsize', default='medium', help='small/medium/large oder Pixel')
    parser.add_argument('--layout', choices=['left', 'centered'], default='left', help='Textausrichtung (default: left)')
    
    args = parser.parse_args()
    
    # \n in echte Zeilenumbrüche umwandeln
    text = args.text.replace('\\n', '\n')
    
    create_text_frame(text, args.size, args.template, args.font, args.fontsize, args.layout)

if __name__ == '__main__':
    main()
