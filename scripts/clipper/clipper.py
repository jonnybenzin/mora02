#!/usr/bin/env python3
"""
Mora02 - Clipper v3.2
- Flüssige 30fps Animation
- Ease In/Out Bewegung
- Hohe Qualität (CRF 18)
"""

import os
import sys
import shutil
import subprocess
import tempfile
import math
import re
from pathlib import Path
from datetime import datetime

# ============================================================================
# KONFIGURATION
# ============================================================================

BASE_DIR = "/opt/mora02/output/_default/clipper"
INPUT_DIR = f"{BASE_DIR}/source"
ARCHIVE_BASE = BASE_DIR

IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.webp', '.bmp')
VIDEO_EXTENSIONS = ('.mp4', '.mov', '.webm', '.avi', '.mkv')

RESOLUTION_PRESETS = {
    '1080p': (1920, 1080), '720p': (1280, 720), '4k': (3840, 2160),
    'square': (1080, 1080), 'story': (1080, 1920), 'reels': (1080, 1920),
    'fb-link': (1200, 628), 'twitter': (1200, 675), 'linkedin': (1200, 627),
}

PARALLAX_SPEEDS = {'bg': 0.3, 'mg': 0.6, 'fg': 1.0}

OVERLAY_POSITIONS = {
    'center': '(W-w)/2:(H-h)/2', 'top-left': '20:20', 'top-right': 'W-w-20:20',
    'bottom-left': '20:H-h-20', 'bottom-right': 'W-w-20:H-h-20',
}

DEFAULT_FPS = 30
DEFAULT_DURATION = 4.0
DEFAULT_TRANSITION = 1.0
DEFAULT_DIRECTION = 0
DEFAULT_INTENSITY = 20
DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080

# Qualitäts-Einstellungen
CRF_QUALITY = 18  # 0=lossless, 18=sehr gut, 23=default, 28=klein
PRESET = 'slow'   # slower = bessere Qualität

# ============================================================================
# LOGGING
# ============================================================================

class Logger:
    def __init__(self):
        self.log_buffer = []
        self.log_file = None
        
    def set_log_file(self, log_file):
        self.log_file = log_file
        
    def log(self, message):
        print(message)
        self.log_buffer.append(message)
    
    def save(self):
        if not self.log_file:
            return
        try:
            with open(self.log_file, 'w', encoding='utf-8') as f:
                f.write("# Mora02 Clipper v3.2 - Log\n\n")
                f.write(f"**Erstellt:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                f.write("```\n")
                f.write('\n'.join(self.log_buffer))
                f.write("\n```\n")
        except:
            pass

# ============================================================================
# AUFLÖSUNGS-PARSER
# ============================================================================

def parse_resolution(resolution_str):
    resolution_str = resolution_str.strip().lower()
    if resolution_str in RESOLUTION_PRESETS:
        return RESOLUTION_PRESETS[resolution_str]
    match = re.match(r'^(\d+)\s*[xX×]\s*(\d+)$', resolution_str)
    if match:
        return (int(match.group(1)), int(match.group(2)))
    if resolution_str.isdigit():
        width = int(resolution_str)
        return (width, int(width * 9 / 16))
    return (DEFAULT_WIDTH, DEFAULT_HEIGHT)

def format_resolution_help():
    presets = ", ".join(RESOLUTION_PRESETS.keys())
    return f"BxH (z.B. 1920x1080) oder Preset: {presets}"

# ============================================================================
# 360° ANIMATIONS-SYSTEM MIT EASE IN/OUT
# ============================================================================

def direction_to_vector(degrees, intensity):
    radians = math.radians(degrees - 90)
    dx = math.cos(radians) * intensity
    dy = math.sin(radians) * intensity
    return dx, dy

def build_pan_filter(direction, intensity, duration, width, height, fps):
    """
    Pan-Animation mit Ease In/Out
    
    Ease In/Out Formel (Smooth Step):
    t = on/d (0 bis 1)
    ease = t * t * (3 - 2 * t)
    
    In ffmpeg Expression:
    ease = (on/d)*(on/d)*(3-2*(on/d))
    """
    frames = max(int(duration * fps), 2)
    dx, dy = direction_to_vector(direction, intensity)
    
    zoom = 1.0 + (intensity / 100) * 0.5
    
    start_x = 0.5 - (dx / 200)
    start_y = 0.5 - (dy / 200)
    end_x = 0.5 + (dx / 200)
    end_y = 0.5 + (dy / 200)
    
    delta_x = end_x - start_x
    delta_y = end_y - start_y
    
    # Ease In/Out: t*t*(3-2*t) wobei t = on/frames
    ease_expr = f"((on/{frames})*(on/{frames})*(3-2*(on/{frames})))"
    
    x_expr = f"iw*({start_x}+{delta_x}*{ease_expr})-iw/2/{zoom}"
    y_expr = f"ih*({start_y}+{delta_y}*{ease_expr})-ih/2/{zoom}"
    
    return f"zoompan=z={zoom}:x='{x_expr}':y='{y_expr}':d={frames}:s={width}x{height}:fps={fps}"

def build_zoom_filter(zoom_type, direction, intensity, duration, width, height, fps):
    """
    Zoom-Animation mit Ease In/Out
    """
    frames = max(int(duration * fps), 2)
    dx, dy = direction_to_vector(direction, intensity)
    
    focus_x = max(0.2, min(0.8, 0.5 + (dx / 200)))
    focus_y = max(0.2, min(0.8, 0.5 + (dy / 200)))
    
    zoom_amount = 1 + (intensity / 100)
    
    # Ease In/Out für Zoom
    ease_expr = f"((on/{frames})*(on/{frames})*(3-2*(on/{frames})))"
    
    if zoom_type == 'zoom_in':
        # Von 1.0 zu zoom_amount mit ease
        z_expr = f"1+({zoom_amount}-1)*{ease_expr}"
    else:
        # Von zoom_amount zu 1.0 mit ease
        z_expr = f"{zoom_amount}-({zoom_amount}-1)*{ease_expr}"
    
    x_expr = f"iw*{focus_x}-(iw/zoom/2)"
    y_expr = f"ih*{focus_y}-(ih/zoom/2)"
    
    return f"zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}':d={frames}:s={width}x{height}:fps={fps}"

def build_animation_filter(anim_type, direction, intensity, duration, width, height, fps):
    if anim_type == 'none' or anim_type is None:
        return f'scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2'
    elif anim_type == 'pan':
        return build_pan_filter(direction, intensity, duration, width, height, fps)
    elif anim_type in ('zoom_in', 'zoom_out'):
        return build_zoom_filter(anim_type, direction, intensity, duration, width, height, fps)
    else:
        return f'scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2'

# ============================================================================
# HILFSFUNKTIONEN
# ============================================================================

def create_timestamp():
    return datetime.now().strftime("%Y%m%d%H%M")

def check_ffmpeg():
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        return True
    except:
        return False

def get_video_duration(video_path):
    cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
           '-of', 'default=noprint_wrappers=1:nokey=1', str(video_path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return float(result.stdout.strip())
    except:
        return 0

def natural_sort_key(s):
    return [int(text) if text.isdigit() else text.lower() 
            for text in re.split(r'(\d+)', str(s))]

def find_media_files(directory):
    media = []
    dir_path = Path(directory)
    
    for file in dir_path.glob("*"):
        if file.is_dir():
            continue
        ext = file.suffix.lower()
        if ext in IMAGE_EXTENSIONS or ext in VIDEO_EXTENSIONS:
            name = file.stem
            if len(name) >= 1 and name[0].isdigit():
                media_type = 'image' if ext in IMAGE_EXTENSIONS else 'video'
                media.append({'path': file, 'type': media_type, 'name': file.name})
    
    return sorted(media, key=lambda x: natural_sort_key(x['name']))

def find_overlay_sequence(overlay_dir):
    if not overlay_dir or not Path(overlay_dir).exists():
        return None
    
    overlay_path = Path(overlay_dir)
    png_files = sorted(overlay_path.glob("*.png"), key=lambda x: natural_sort_key(x.name))
    
    if not png_files:
        return None
    
    first_file = png_files[0]
    name = first_file.stem
    
    if name.isdigit():
        ffmpeg_pattern = f"%0{len(name)}d.png"
    else:
        for i, char in enumerate(name):
            if char.isdigit():
                prefix = name[:i]
                num_part = name[i:]
                if num_part.isdigit():
                    ffmpeg_pattern = f"{prefix}%0{len(num_part)}d.png"
                    break
        else:
            return None
    
    return {'path': overlay_path, 'pattern': ffmpeg_pattern, 'count': len(png_files), 'files': png_files}

def find_parallax_layers(layers_dir):
    if not layers_dir or not Path(layers_dir).exists():
        return None
    
    layers_path = Path(layers_dir)
    layers = {}
    
    for layer_name in ['bg', 'mg', 'fg']:
        layer_path = layers_path / layer_name
        if not layer_path.exists():
            continue
        
        png_files = sorted(layer_path.glob("*.png"), key=lambda x: natural_sort_key(x.name))
        
        if len(png_files) > 1:
            seq_info = find_overlay_sequence(layer_path)
            if seq_info:
                layers[layer_name] = {'type': 'sequence', 'data': seq_info}
        elif len(png_files) == 1:
            layers[layer_name] = {'type': 'image', 'data': png_files[0]}
    
    return layers if layers else None

def parse_array_input(input_str, count, default_value, max_value=None, is_int=False):
    if not input_str or not input_str.strip():
        return [default_value] * count
    
    try:
        input_str = re.sub(r'\s*,\s*', ',', input_str.strip()).rstrip(',')
        
        if ',' in input_str:
            parts = [p.strip() for p in input_str.split(',') if p.strip()]
            values = [int(float(v)) if is_int else float(v) for v in parts]
        else:
            single = int(float(input_str)) if is_int else float(input_str)
            return [single] * count
        
        if max_value is not None:
            values = [min(v, max_value) for v in values]
        values = [max(0, v) for v in values]
        
        while len(values) < count:
            values.append(default_value)
        
        return values[:count]
    except:
        return [default_value] * count

def parse_animation_array(input_str, count, default_value='pan'):
    if not input_str or not input_str.strip():
        return [default_value] * count
    
    input_str = re.sub(r'\s*,\s*', ',', input_str.strip()).rstrip(',')
    valid = ('pan', 'zoom_in', 'zoom_out', 'none')
    
    if ',' in input_str:
        parts = [p.strip().lower() for p in input_str.split(',') if p.strip()]
        values = [p if p in valid else default_value for p in parts]
    else:
        single = input_str.strip().lower()
        return [single if single in valid else default_value] * count
    
    while len(values) < count:
        values.append(default_value)
    
    return values[:count]

def get_direction_arrow(degrees):
    degrees = degrees % 360
    arrows = {0: '↑', 45: '↗', 90: '→', 135: '↘', 180: '↓', 225: '↙', 270: '←', 315: '↖'}
    closest = min(arrows.keys(), key=lambda x: min(abs(x - degrees), 360 - abs(x - degrees)))
    return arrows[closest]

# ============================================================================
# VIDEO ERSTELLUNG (HOHE QUALITÄT)
# ============================================================================

def create_animated_clip(image_path, output_path, duration, anim_type, direction, intensity, 
                         width, height, fps, logger):
    
    filter_str = build_animation_filter(anim_type, direction, intensity, duration, width, height, fps)
    
    # Hohe Qualität: CRF 18, preset slow
    if anim_type == 'none':
        cmd = [
            'ffmpeg', '-y', '-loop', '1', '-i', str(image_path),
            '-vf', filter_str,
            '-c:v', 'libx264', '-crf', str(CRF_QUALITY), '-preset', PRESET,
            '-t', str(duration), '-pix_fmt', 'yuv420p', '-r', str(fps),
            str(output_path)
        ]
    else:
        cmd = [
            'ffmpeg', '-y', '-i', str(image_path),
            '-vf', filter_str,
            '-c:v', 'libx264', '-crf', str(CRF_QUALITY), '-preset', PRESET,
            '-pix_fmt', 'yuv420p',
            str(output_path)
        ]
    
    direction_arrow = get_direction_arrow(direction)
    logger.log(f"   🎨 {anim_type} {direction}° {direction_arrow}, {intensity}%, {duration}s")
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.log(f"   ⚠️  ffmpeg Fehler: {result.stderr[:200]}")
        return False
    return True

def prepare_video_clip(video_path, output_path, width, height, fps, logger):
    filter_str = f'scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps={fps}'
    
    cmd = [
        'ffmpeg', '-y', '-i', str(video_path),
        '-vf', filter_str,
        '-c:v', 'libx264', '-crf', str(CRF_QUALITY), '-preset', PRESET,
        '-pix_fmt', 'yuv420p', '-an',
        str(output_path)
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.log(f"   ⚠️  ffmpeg Fehler: {result.stderr[:200]}")
        return False
    return True

def concatenate_with_transitions(clip_paths, clip_durations, transitions, output_path, logger):
    if len(clip_paths) == 0:
        return False
    
    if len(clip_paths) == 1:
        shutil.copy(clip_paths[0], output_path)
        return True
    
    # Übergänge validieren
    validated_transitions = []
    for i, trans_dur in enumerate(transitions):
        if i < len(clip_durations) - 1:
            max_trans = min(clip_durations[i], clip_durations[i + 1]) * 0.9
            if trans_dur > max_trans:
                logger.log(f"   ⚠️  Übergang {i+1} gekürzt: {trans_dur}s → {max_trans:.2f}s")
                trans_dur = max(0, max_trans)
        validated_transitions.append(trans_dur)
    transitions = validated_transitions
    
    all_hard_cuts = all(t == 0 for t in transitions)
    
    if all_hard_cuts:
        logger.log("\n🔗 Verkette Clips (harte Schnitte)...")
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            for clip in clip_paths:
                f.write(f"file '{clip}'\n")
            concat_file = f.name
        
        cmd = [
            'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', concat_file,
            '-c:v', 'libx264', '-crf', str(CRF_QUALITY), '-preset', PRESET,
            '-pix_fmt', 'yuv420p', str(output_path)
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        os.unlink(concat_file)
        return result.returncode == 0
    
    logger.log(f"\n🔗 Verkette Clips mit Übergängen...")
    
    current = clip_paths[0]
    current_duration = clip_durations[0]
    
    for i, (next_clip, trans_dur) in enumerate(zip(clip_paths[1:], transitions)):
        temp_output = tempfile.NamedTemporaryFile(suffix='.mp4', delete=False).name
        
        if trans_dur == 0:
            logger.log(f"   [{i+1}→{i+2}] Harter Schnitt")
            
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
                f.write(f"file '{current}'\n")
                f.write(f"file '{next_clip}'\n")
                concat_file = f.name
            
            cmd = [
                'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', concat_file,
                '-c:v', 'libx264', '-crf', str(CRF_QUALITY), '-preset', PRESET,
                '-pix_fmt', 'yuv420p', temp_output
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            os.unlink(concat_file)
        else:
            logger.log(f"   [{i+1}→{i+2}] Crossfade {trans_dur:.2f}s")
            
            offset = max(0, current_duration - trans_dur)
            
            cmd = [
                'ffmpeg', '-y',
                '-i', str(current), '-i', str(next_clip),
                '-filter_complex', f'xfade=transition=fade:duration={trans_dur}:offset={offset}',
                '-c:v', 'libx264', '-crf', str(CRF_QUALITY), '-preset', PRESET,
                '-pix_fmt', 'yuv420p', temp_output
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            logger.log(f"   ⚠️  Fehler, verwende Hard Cut")
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
                f.write(f"file '{current}'\n")
                f.write(f"file '{next_clip}'\n")
                concat_file = f.name
            cmd = ['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', concat_file,
                   '-c:v', 'libx264', '-crf', str(CRF_QUALITY), '-pix_fmt', 'yuv420p', temp_output]
            subprocess.run(cmd, capture_output=True)
            os.unlink(concat_file)
        
        if i > 0 and current != clip_paths[0]:
            try: os.unlink(current)
            except: pass
        
        current = temp_output
        current_duration = get_video_duration(current)
    
    shutil.move(current, output_path)
    return True

def apply_overlay(video_path, overlay_info, output_path, position, scale, loop, start_offset, fps, logger):
    video_duration = get_video_duration(video_path)
    overlay_duration = overlay_info['count'] / fps
    
    logger.log(f"\n🎭 Overlay: {overlay_info['count']} Frames ({overlay_duration:.1f}s)")
    
    pos_str = OVERLAY_POSITIONS.get(position, OVERLAY_POSITIONS['center'])
    seq_pattern = str(overlay_info['path'] / overlay_info['pattern'])
    
    scale_filter = f"scale=iw*{scale}:ih*{scale}" if scale != 1.0 else "copy"
    
    if loop and overlay_duration < video_duration:
        loop_count = int(video_duration / overlay_duration) + 1
        filter_complex = f"[1:v]{scale_filter},loop=loop={loop_count}:size={overlay_info['count']}:start=0[ovr];[0:v][ovr]overlay={pos_str}:shortest=1"
    else:
        if start_offset > 0:
            filter_complex = f"[1:v]{scale_filter}[ovr];[0:v][ovr]overlay={pos_str}:enable='gte(t,{start_offset})'"
        else:
            filter_complex = f"[1:v]{scale_filter}[ovr];[0:v][ovr]overlay={pos_str}:shortest=1"
    
    cmd = [
        'ffmpeg', '-y', '-i', str(video_path), '-framerate', str(fps), '-i', seq_pattern,
        '-filter_complex', filter_complex,
        '-c:v', 'libx264', '-crf', str(CRF_QUALITY), '-preset', PRESET,
        '-pix_fmt', 'yuv420p', str(output_path)
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        shutil.copy(video_path, output_path)
        return False
    
    logger.log(f"   ✅ Overlay OK")
    return True

def apply_parallax_layers(video_path, layers, output_path, direction, intensity, fps, logger):
    logger.log(f"\n🎭 Parallax: {direction}° {get_direction_arrow(direction)}, {intensity}px")
    
    video_duration = get_video_duration(video_path)
    dx, dy = direction_to_vector(direction, intensity)
    
    current_video = video_path
    temp_files = []
    
    for layer_name in ['bg', 'mg', 'fg']:
        if layer_name not in layers:
            continue
        
        layer = layers[layer_name]
        speed = PARALLAX_SPEEDS[layer_name]
        layer_dx = dx * speed
        layer_dy = dy * speed
        
        logger.log(f"   {layer_name}: {speed}x")
        
        temp_output = tempfile.NamedTemporaryFile(suffix='.mp4', delete=False).name
        temp_files.append(temp_output)
        
        if layer['type'] == 'sequence':
            seq_info = layer['data']
            seq_pattern = str(seq_info['path'] / seq_info['pattern'])
            filter_complex = f"[1:v]format=rgba[ovr];[0:v][ovr]overlay=(W-w)/2:(H-h)/2:shortest=1"
            cmd = [
                'ffmpeg', '-y', '-i', str(current_video), '-framerate', str(fps), '-i', seq_pattern,
                '-filter_complex', filter_complex,
                '-c:v', 'libx264', '-crf', str(CRF_QUALITY), '-pix_fmt', 'yuv420p', temp_output
            ]
        else:
            image_path = layer['data']
            filter_complex = (
                f"[1:v]scale=iw*1.2:ih*1.2,format=rgba,"
                f"crop=iw/{1.2}:ih/{1.2}:"
                f"(iw-iw/{1.2})/2+(({layer_dx})*t/{video_duration}):"
                f"(ih-ih/{1.2})/2+(({layer_dy})*t/{video_duration})[ovr];"
                f"[0:v][ovr]overlay=(W-w)/2:(H-h)/2"
            )
            cmd = [
                'ffmpeg', '-y', '-i', str(current_video), '-loop', '1', '-t', str(video_duration),
                '-i', str(image_path), '-filter_complex', filter_complex,
                '-c:v', 'libx264', '-crf', str(CRF_QUALITY), '-pix_fmt', 'yuv420p',
                '-t', str(video_duration), temp_output
            ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            continue
        current_video = temp_output
    
    if current_video != video_path:
        shutil.move(current_video, output_path)
    else:
        shutil.copy(video_path, output_path)
    
    for tf in temp_files[:-1]:
        try: os.unlink(tf)
        except: pass
    
    logger.log(f"   ✅ Parallax OK")
    return True

def add_audio(video_path, audio_path, output_path, logger):
    cmd = [
        'ffmpeg', '-y', '-i', str(video_path), '-i', str(audio_path),
        '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
        '-shortest', '-map', '0:v:0', '-map', '1:a:0', str(output_path)
    ]
    return subprocess.run(cmd, capture_output=True).returncode == 0

# ============================================================================
# INTERAKTIVE ABFRAGE
# ============================================================================

def prompt_with_default(prompt, default):
    result = input(f"{prompt} [{default}]: ").strip()
    return result if result else str(default)

def prompt_yes_no(prompt, default=True):
    default_str = "J/n" if default else "j/N"
    result = input(f"{prompt} [{default_str}]: ").strip().lower()
    return result in ('j', 'ja', 'y', 'yes', '') if default else result in ('j', 'ja', 'y', 'yes')

def get_parameters():
    print("\n" + "=" * 60)
    print("Mora02 - Clipper v3.2 (Ease In/Out + HQ)")
    print("=" * 60 + "\n")
    
    input_dir = prompt_with_default("Quell-Ordner", INPUT_DIR)
    
    media = find_media_files(input_dir)
    if not media:
        print(f"\n❌ Keine Medien in {input_dir} gefunden!")
        return None
    
    image_count = sum(1 for m in media if m['type'] == 'image')
    video_count = sum(1 for m in media if m['type'] == 'video')
    
    print(f"\n✅ {len(media)} Medien ({image_count} Bilder, {video_count} Videos):")
    for idx, m in enumerate(media[:10], 1):
        icon = "🖼️" if m['type'] == 'image' else "🎬"
        print(f"   {idx}. {icon} {m['name']}")
    if len(media) > 10:
        print(f"   ... und {len(media) - 10} weitere")
    
    overlay_dir = Path(input_dir) / "overlay"
    layers_dir = Path(input_dir) / "layers"
    overlay_info = find_overlay_sequence(overlay_dir)
    parallax_layers = find_parallax_layers(layers_dir)
    
    if overlay_info:
        print(f"\n🎭 Overlay: {overlay_info['count']} Frames")
    if parallax_layers:
        print(f"🎭 Parallax: {', '.join(parallax_layers.keys())}")
    
    # AUFLÖSUNG
    print("\n--- Auflösung ---")
    print(f"  {format_resolution_help()}")
    resolution_input = prompt_with_default("Auflösung", "1920x1080")
    width, height = parse_resolution(resolution_input)
    print(f"  → {width}x{height}")
    
    # CLIP-PARAMETER
    print("\n--- Clip-Parameter ---")
    duration_input = prompt_with_default(f"Dauern für {image_count} Bilder (Sek)", str(DEFAULT_DURATION))
    
    # ANIMATION
    print("\n--- Animation (360° mit Ease In/Out) ---")
    print("  Typen: pan, zoom_in, zoom_out, none")
    anim_input = prompt_with_default("Typ(en)", "pan")
    anim_types = parse_animation_array(anim_input, image_count, 'pan')
    
    all_none = all(a == 'none' for a in anim_types)
    
    if not all_none:
        print("\n  Richtung: 0°=↑  90°=→  180°=↓  270°=←")
        direction_input = prompt_with_default("Richtung(en) (0-360°)", str(DEFAULT_DIRECTION))
        intensity_input = prompt_with_default("Intensität(en) (%)", str(DEFAULT_INTENSITY))
    else:
        direction_input = "0"
        intensity_input = "0"
    
    # ÜBERGÄNGE
    print("\n--- Übergänge ---")
    num_transitions = len(media) - 1
    if num_transitions > 0:
        print(f"  {num_transitions} Übergänge, 0=harter Schnitt")
        transition_input = prompt_with_default("Dauern (0-3 Sek)", str(DEFAULT_TRANSITION))
    else:
        transition_input = "0"
    
    # OVERLAY
    overlay_params = None
    if overlay_info:
        print("\n--- Overlay ---")
        if prompt_yes_no("Verwenden?", True):
            overlay_position = prompt_with_default("Position (center/top-left/...)", "center")
            overlay_scale = float(prompt_with_default("Skalierung", "1.0"))
            overlay_loop = prompt_yes_no("Loop?", True)
            overlay_offset = float(prompt_with_default("Verzögerung (Sek)", "0"))
            overlay_params = {
                'info': overlay_info, 'position': overlay_position,
                'scale': max(0.1, min(2.0, overlay_scale)),
                'loop': overlay_loop, 'offset': overlay_offset
            }
    
    # PARALLAX
    parallax_params = None
    if parallax_layers:
        print("\n--- Parallax ---")
        if prompt_yes_no("Verwenden?", True):
            parallax_direction = int(prompt_with_default("Richtung (0-360°)", "90"))
            parallax_intensity = int(prompt_with_default("Intensität (px)", "50"))
            parallax_params = {
                'layers': parallax_layers,
                'direction': parallax_direction,
                'intensity': parallax_intensity
            }
    
    # OUTPUT
    print("\n--- Output ---")
    audio = prompt_with_default("Audio (leer=stumm)", "")
    output_name = prompt_with_default("Dateiname", "output.mp4")
    if not output_name.endswith('.mp4'):
        output_name += '.mp4'
    
    return {
        'input_dir': input_dir, 'media': media, 'width': width, 'height': height,
        'duration_input': duration_input, 'anim_types': anim_types,
        'direction_input': direction_input, 'intensity_input': intensity_input,
        'transition_input': transition_input, 'overlay': overlay_params,
        'parallax': parallax_params, 'audio': audio if audio else None,
        'output_name': output_name
    }

# ============================================================================
# ARCHIVIERUNG
# ============================================================================

def archive_files(media, overlay_info, parallax_layers, archive_dir, logger):
    source_archive = archive_dir / "source"
    source_archive.mkdir(exist_ok=True)
    
    for m in media:
        shutil.copy2(m['path'], source_archive / m['path'].name)
    
    if overlay_info:
        overlay_archive = source_archive / "overlay"
        overlay_archive.mkdir(exist_ok=True)
        for f in overlay_info['files']:
            shutil.copy2(f, overlay_archive / f.name)
    
    if parallax_layers:
        layers_archive = source_archive / "layers"
        layers_archive.mkdir(exist_ok=True)
        for layer_name, layer in parallax_layers.items():
            layer_dir = layers_archive / layer_name
            layer_dir.mkdir(exist_ok=True)
            if layer['type'] == 'sequence':
                for f in layer['data']['files']:
                    shutil.copy2(f, layer_dir / f.name)
            else:
                shutil.copy2(layer['data'], layer_dir / layer['data'].name)
    
    logger.log(f"\n📦 Archiviert: {archive_dir}")

def cleanup_source(input_dir, has_overlay, has_parallax, logger):
    for file in Path(input_dir).iterdir():
        if file.is_dir():
            if file.name == "overlay" and has_overlay:
                shutil.rmtree(file)
            elif file.name == "layers" and has_parallax:
                shutil.rmtree(file)
            continue
        ext = file.suffix.lower()
        if ext in IMAGE_EXTENSIONS or ext in VIDEO_EXTENSIONS:
            file.unlink()
    logger.log(f"🧹 Source aufgeräumt")

# ============================================================================
# HAUPTPROGRAMM
# ============================================================================

def main():
    logger = Logger()
    
    if not check_ffmpeg():
        print("❌ ffmpeg nicht gefunden!")
        sys.exit(1)
    
    params = get_parameters()
    if not params:
        sys.exit(1)
    
    timestamp = create_timestamp()
    width, height = params['width'], params['height']
    fps = DEFAULT_FPS
    
    media = params['media']
    image_count = sum(1 for m in media if m['type'] == 'image')
    
    durations = parse_array_input(params['duration_input'], image_count, DEFAULT_DURATION)
    anim_types = params['anim_types']
    directions = parse_array_input(params['direction_input'], image_count, DEFAULT_DIRECTION, max_value=360, is_int=True)
    intensities = parse_array_input(params['intensity_input'], image_count, DEFAULT_INTENSITY)
    transitions = parse_array_input(params['transition_input'], len(media) - 1, DEFAULT_TRANSITION, max_value=3.0)
    
    temp_dir = tempfile.mkdtemp(prefix='clipper_')
    archive_dir = Path(ARCHIVE_BASE) / f"{timestamp}_clipper"
    archive_dir.mkdir(parents=True, exist_ok=True)
    
    log_dir = archive_dir / "source"
    log_dir.mkdir(exist_ok=True)
    logger.set_log_file(log_dir / f"{timestamp}_logs.md")
    
    logger.log("\n" + "=" * 60)
    logger.log("Mora02 - Clipper v3.2 (Ease In/Out + HQ)")
    logger.log("=" * 60)
    logger.log(f"\n📁 {params['input_dir']}")
    logger.log(f"📐 {width}x{height} @ {fps}fps")
    logger.log(f"🎨 Animationen: {anim_types}")
    logger.log(f"🎬 Qualität: CRF {CRF_QUALITY}, Preset {PRESET}")
    
    # CLIPS ERSTELLEN
    logger.log(f"\n🎬 Erstelle {len(media)} Clips...")
    
    clip_paths = []
    clip_durations = []
    duration_idx = 0
    
    for idx, m in enumerate(media, 1):
        logger.log(f"\n[{idx}/{len(media)}] {m['name']}")
        
        clip_path = Path(temp_dir) / f"clip_{idx:03d}.mp4"
        
        if m['type'] == 'image':
            clip_dur = durations[duration_idx] if duration_idx < len(durations) else DEFAULT_DURATION
            anim_type = anim_types[duration_idx] if duration_idx < len(anim_types) else 'pan'
            direction = directions[duration_idx] if duration_idx < len(directions) else DEFAULT_DIRECTION
            intensity = intensities[duration_idx] if duration_idx < len(intensities) else DEFAULT_INTENSITY
            duration_idx += 1
            
            success = create_animated_clip(
                m['path'], clip_path, clip_dur, anim_type,
                direction, intensity, width, height, fps, logger
            )
            
            if success and clip_path.exists():
                clip_durations.append(get_video_duration(clip_path))
        else:
            logger.log(f"   🎬 Video")
            success = prepare_video_clip(m['path'], clip_path, width, height, fps, logger)
            
            if success and clip_path.exists():
                actual_dur = get_video_duration(clip_path)
                clip_durations.append(actual_dur)
                logger.log(f"   ⏱️  {actual_dur:.1f}s")
        
        if success and clip_path.exists():
            clip_paths.append(str(clip_path))
            logger.log(f"   ✅ OK")
        else:
            logger.log(f"   ❌ Fehler")
    
    if not clip_paths:
        logger.log("\n❌ Keine Clips!")
        shutil.rmtree(temp_dir)
        sys.exit(1)
    
    # ZUSAMMENFÜGEN
    temp_output = Path(temp_dir) / "temp_final.mp4"
    concatenate_with_transitions(clip_paths, clip_durations, transitions, str(temp_output), logger)
    
    # PARALLAX
    if params['parallax']:
        parallax_output = Path(temp_dir) / "with_parallax.mp4"
        apply_parallax_layers(
            temp_output, params['parallax']['layers'], parallax_output,
            params['parallax']['direction'], params['parallax']['intensity'], fps, logger
        )
        temp_output = parallax_output
    
    # OVERLAY
    if params['overlay']:
        overlay_output = Path(temp_dir) / "with_overlay.mp4"
        apply_overlay(
            temp_output, params['overlay']['info'], overlay_output,
            params['overlay']['position'], params['overlay']['scale'],
            params['overlay']['loop'], params['overlay']['offset'], fps, logger
        )
        temp_output = overlay_output
    
    # AUDIO
    final_output = archive_dir / params['output_name']
    
    if params['audio'] and Path(params['audio']).exists():
        logger.log(f"\n🎵 Audio: {params['audio']}")
        audio_output = Path(temp_dir) / "with_audio.mp4"
        if add_audio(temp_output, params['audio'], audio_output, logger):
            shutil.move(audio_output, final_output)
        else:
            shutil.move(temp_output, final_output)
    else:
        shutil.move(temp_output, final_output)
    
    # STATISTIKEN
    final_duration = get_video_duration(final_output)
    file_size = final_output.stat().st_size / (1024 * 1024)
    
    logger.log(f"\n✅ Fertig: {final_output.name}")
    logger.log(f"   📐 {width}x{height}")
    logger.log(f"   📊 {file_size:.2f} MB, {final_duration:.1f}s")
    
    # ARCHIVIEREN
    overlay_info = params['overlay']['info'] if params['overlay'] else None
    parallax_layers = params['parallax']['layers'] if params['parallax'] else None
    
    archive_files(media, overlay_info, parallax_layers, archive_dir, logger)
    cleanup_source(params['input_dir'], params['overlay'] is not None, params['parallax'] is not None, logger)
    
    shutil.rmtree(temp_dir)
    logger.save()
    
    print(f"\n📁 Output: {final_output}")

if __name__ == "__main__":
    main()
