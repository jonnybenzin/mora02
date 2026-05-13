#!/usr/bin/env python3
"""
Clipper API Module - Wrapper for clipper script functionality
For use with Script Runner FastAPI service

v1.1.1 - Audio support for video inputs (bug fix)
"""

import subprocess
import tempfile
import shutil
import math
import re
from pathlib import Path
from typing import List, Dict, Any

# Resolution presets
RESOLUTION_PRESETS = {
    '1080p': (1920, 1080),
    '720p': (1280, 720),
    '4k': (3840, 2160),
    'square': (1080, 1080),
    'story': (1080, 1920),
    'reels': (1080, 1920),
}

IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.webp', '.bmp')
VIDEO_EXTENSIONS = ('.mp4', '.mov', '.webm', '.avi', '.mkv')

DEFAULT_FPS = 30
CRF_QUALITY = 18
PRESET = 'medium'

def parse_resolution(resolution_str: str) -> tuple:
    resolution_str = resolution_str.strip().lower()
    if resolution_str in RESOLUTION_PRESETS:
        return RESOLUTION_PRESETS[resolution_str]
    match = re.match(r'^(\d+)\s*[xX×]\s*(\d+)$', resolution_str)
    if match:
        return (int(match.group(1)), int(match.group(2)))
    if resolution_str.isdigit():
        width = int(resolution_str)
        return (width, int(width * 9 / 16))
    return (1920, 1080)

def parse_array_input(input_str: str, count: int, default: float) -> List[float]:
    parts = [p.strip() for p in input_str.replace(' ', ',').split(',') if p.strip()]
    values = []
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

def direction_to_vector(degrees: float, intensity: float) -> tuple:
    radians = math.radians(degrees - 90)
    dx = math.cos(radians) * intensity
    dy = math.sin(radians) * intensity
    return dx, dy

def aspect_crop(width: int, height: int) -> str:
    """Crop input to match target aspect ratio (cover/fill mode)"""
    return f"crop=if(gt(iw/ih\,{width}/{height})\,ih*{width}/{height}\,iw):if(gt(iw/ih\,{width}/{height})\,ih\,iw*{height}/{width})"

def build_animation_filter(anim_type: str, direction: float, intensity: float, duration: float, width: int, height: int, fps: int) -> str:
    frames = max(int(duration * fps), 2)
    if anim_type == 'none':
        return f'{aspect_crop(width, height)},scale={width}:{height}'
    dx, dy = direction_to_vector(direction, intensity)
    ease_expr = f"((on/{frames})*(on/{frames})*(3-2*(on/{frames})))"
    if anim_type == 'pan':
        zoom = 1.0 + (intensity / 100) * 0.5
        start_x = 0.5 - (dx / 200)
        start_y = 0.5 - (dy / 200)
        delta_x = dx / 100
        delta_y = dy / 100
        x_expr = f"iw*({start_x}+{delta_x}*{ease_expr})-iw/2/{zoom}"
        y_expr = f"ih*({start_y}+{delta_y}*{ease_expr})-ih/2/{zoom}"
        ac = aspect_crop(width, height)
        return f"{ac},zoompan=z={zoom}:x='{x_expr}':y='{y_expr}':d={frames}:s={width}x{height}:fps={fps}"
    elif anim_type in ('zoom_in', 'zoom_out'):
        focus_x = max(0.2, min(0.8, 0.5 + (dx / 200)))
        focus_y = max(0.2, min(0.8, 0.5 + (dy / 200)))
        zoom_amount = 1 + (intensity / 100)
        if anim_type == 'zoom_in':
            z_expr = f"1+({zoom_amount}-1)*{ease_expr}"
        else:
            z_expr = f"{zoom_amount}-({zoom_amount}-1)*{ease_expr}"
        x_expr = f"iw*{focus_x}-(iw/zoom/2)"
        y_expr = f"ih*{focus_y}-(ih/zoom/2)"
        ac = aspect_crop(width, height)
        return f"{ac},zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}':d={frames}:s={width}x{height}:fps={fps}"
    return f'{aspect_crop(width, height)},scale={width}:{height}'

def get_video_duration(video_path: Path) -> float:
    cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', str(video_path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return float(result.stdout.strip())
    except (ValueError, TypeError):
        return 0

def video_has_audio(video_path: Path) -> bool:
    cmd = ['ffprobe', '-v', 'error', '-select_streams', 'a', '-show_entries', 'stream=codec_type', '-of', 'csv=p=0', str(video_path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return bool(result.stdout.strip())

def create_clip_from_files(
    input_files: List[Path],
    output_path: Path,
    resolution: str = "1080p",
    durations: str = "4",
    animation: str = "pan",
    direction: str = "90",
    intensity: str = "20",
    transition: str = "1"
) -> Dict[str, Any]:
    try:
        width, height = parse_resolution(resolution)
        fps = DEFAULT_FPS
        
        media = []
        for f in sorted(input_files, key=lambda x: x.name):
            ext = f.suffix.lower()
            if ext in IMAGE_EXTENSIONS:
                media.append({'path': f, 'type': 'image'})
            elif ext in VIDEO_EXTENSIONS:
                media.append({'path': f, 'type': 'video'})
        
        if not media:
            return {"success": False, "error": "No valid media files found"}
        
        image_count = sum(1 for m in media if m['type'] == 'image')
        duration_list = parse_array_input(durations, image_count, 4.0)
        direction_list = parse_array_input(direction, image_count, 90)
        intensity_list = parse_array_input(intensity, image_count, 20)
        
        temp_dir = Path(tempfile.mkdtemp(prefix='clipper_'))
        
        try:
            clip_paths = []
            duration_idx = 0
            
            for idx, m in enumerate(media):
                clip_path = temp_dir / f"clip_{idx:03d}.mp4"
                
                if m['type'] == 'image':
                    # IMAGE: Ken Burns + silent audio
                    dur = duration_list[duration_idx] if duration_idx < len(duration_list) else 4.0
                    dir_val = direction_list[duration_idx] if duration_idx < len(direction_list) else 90
                    int_val = intensity_list[duration_idx] if duration_idx < len(intensity_list) else 20
                    duration_idx += 1
                    
                    filter_str = build_animation_filter(animation, dir_val, int_val, dur, width, height, fps)
                    
                    cmd = [
                        'ffmpeg', '-y',
                        '-loop', '1',
                        '-i', str(m['path']),
                        '-f', 'lavfi',
                        '-i', 'anullsrc=r=44100:cl=stereo',
                        '-vf', filter_str,
                        '-t', str(dur),
                        '-c:v', 'libx264',
                        '-preset', PRESET,
                        '-crf', str(CRF_QUALITY),
                        '-c:a', 'aac',
                        '-b:a', '128k',
                        '-pix_fmt', 'yuv420p',
                        '-shortest',
                        str(clip_path)
                    ]
                    subprocess.run(cmd, capture_output=True, text=True)
                    
                else:
                    # VIDEO: Scale + keep audio (or add silent if none)
                    has_audio = video_has_audio(m['path'])
                    
                    if has_audio:
                        # Video WITH audio - scale video, keep audio
                        cmd = [
                            'ffmpeg', '-y',
                            '-i', str(m['path']),
                            '-vf', f'{aspect_crop(width, height)},scale={width}:{height}',
                            '-c:v', 'libx264',
                            '-preset', PRESET,
                            '-crf', str(CRF_QUALITY),
                            '-r', str(fps),
                            '-c:a', 'aac',
                            '-b:a', '128k',
                            '-pix_fmt', 'yuv420p',
                            str(clip_path)
                        ]
                    else:
                        # Video WITHOUT audio - scale video, add silent audio
                        cmd = [
                            'ffmpeg', '-y',
                            '-i', str(m['path']),
                            '-f', 'lavfi',
                            '-i', 'anullsrc=r=44100:cl=stereo',
                            '-vf', f'{aspect_crop(width, height)},scale={width}:{height}',
                            '-c:v', 'libx264',
                            '-preset', PRESET,
                            '-crf', str(CRF_QUALITY),
                            '-r', str(fps),
                            '-c:a', 'aac',
                            '-b:a', '128k',
                            '-map', '0:v',
                            '-map', '1:a',
                            '-shortest',
                            '-pix_fmt', 'yuv420p',
                            str(clip_path)
                        ]
                    
                    subprocess.run(cmd, capture_output=True, text=True)
                
                if clip_path.exists():
                    clip_paths.append(clip_path)
            
            if not clip_paths:
                return {"success": False, "error": "Failed to create any clips"}
            
            if len(clip_paths) == 1:
                shutil.copy2(clip_paths[0], output_path)
            else:
                concat_file = temp_dir / "concat.txt"
                with open(concat_file, 'w') as f:
                    for clip in clip_paths:
                        f.write(f"file '{clip}'\n")
                
                import json as _json
                clip_meta = _json.dumps({
                    "tool": "clipper", "resolution": resolution,
                    "animation": animation, "direction": direction,
                    "intensity": intensity, "transition": transition,
                    "clips": len(clip_paths),
                    "source_files": [f.name for f in input_files],
                })
                cmd = [
                    'ffmpeg', '-y',
                    '-f', 'concat',
                    '-safe', '0',
                    '-i', str(concat_file),
                    '-c:v', 'libx264',
                    '-preset', PRESET,
                    '-crf', str(CRF_QUALITY),
                    '-c:a', 'aac',
                    '-b:a', '128k',
                    '-metadata', f'comment={clip_meta}',
                    '-metadata', 'artist=mora02 (clipper)',
                    str(output_path)
                ]
                subprocess.run(cmd, capture_output=True, text=True)
            
            if not output_path.exists():
                return {"success": False, "error": "Failed to create final video"}
            
            final_duration = get_video_duration(output_path)
            file_size = output_path.stat().st_size
            final_has_audio = video_has_audio(output_path)
            
            return {
                "success": True,
                "filename": output_path.name,
                "clips": len(clip_paths),
                "dimensions": f"{width}x{height}",
                "duration": f"{final_duration:.1f}s",
                "size_bytes": file_size,
                "has_audio": final_has_audio
            }
            
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
            
    except Exception as e:
        return {"success": False, "error": str(e)}
