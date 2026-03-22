#!/usr/bin/env python3
"""
Gifer API Module - Wrapper for gifer script functionality
For use with Script Runner FastAPI service
"""

from pathlib import Path
from PIL import Image, ImageOps
from typing import List, Optional, Dict, Any

# Quality presets
QUALITY_PRESETS = {
    'low': {'colors': 64, 'optimize': True},
    'medium': {'colors': 128, 'optimize': True},
    'high': {'colors': 256, 'optimize': True},
    'ultra': {'colors': 256, 'optimize': False}
}

def parse_size(size_str: Optional[str]) -> Optional[tuple]:
    """Parse size string like '800x600' or '800' to tuple"""
    if not size_str:
        return None
    
    size_str = size_str.strip().lower()
    
    if 'x' in size_str:
        parts = size_str.split('x')
        return (int(parts[0]), int(parts[1]))
    
    # Width only - height will be calculated
    return (int(size_str), None)

def parse_durations(durations_str: str, num_frames: int) -> List[int]:
    """
    Parse durations string to list of milliseconds
    Input: "1,2,2,4" (seconds)
    Output: [1000, 2000, 2000, 4000] (milliseconds)
    """
    parts = [p.strip() for p in durations_str.replace(' ', ',').split(',') if p.strip()]
    
    durations_sec = []
    for p in parts:
        try:
            durations_sec.append(float(p))
        except ValueError:
            durations_sec.append(1.0)
    
    # Extend or truncate to match frame count
    if len(durations_sec) == 1:
        durations_sec = durations_sec * num_frames
    elif len(durations_sec) < num_frames:
        last = durations_sec[-1] if durations_sec else 1.0
        durations_sec.extend([last] * (num_frames - len(durations_sec)))
    else:
        durations_sec = durations_sec[:num_frames]
    
    # Convert to milliseconds
    return [int(d * 1000) for d in durations_sec]

def get_target_dimensions(images: List[Path], user_size: Optional[tuple]) -> tuple:
    """Calculate target dimensions for GIF frames"""
    if not images:
        return (800, 600)
    
    # Get first image dimensions as reference
    ref_img = Image.open(images[0])
    original_ratio = ref_img.width / ref_img.height
    
    if user_size:
        width, height = user_size
        if height is None:
            height = int(width / original_ratio)
        return (width, height)
    
    # Find smallest image
    min_area = float('inf')
    target_dims = (ref_img.width, ref_img.height)
    
    for img_path in images:
        img = Image.open(img_path)
        area = img.width * img.height
        if area < min_area:
            min_area = area
            target_dims = (img.width, img.height)
    
    return target_dims

def standardize_image(img: Image.Image, width: int, height: int) -> Image.Image:
    """Scale and crop image to target dimensions"""
    return ImageOps.fit(
        img,
        (width, height),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5)
    )

def create_gif_from_files(
    input_files: List[Path],
    output_path: Path,
    durations: str,
    quality: str = "medium",
    size: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create GIF from list of image files
    
    Args:
        input_files: List of image file paths (sorted)
        output_path: Where to save the GIF
        durations: Comma-separated durations in seconds
        quality: Quality preset (low, medium, high, ultra)
        size: Target size like "800x600" or "800"
    
    Returns:
        Dict with success status, error message if failed
    """
    try:
        # Filter and sort image files
        image_extensions = ('.jpg', '.jpeg', '.png', '.bmp', '.webp')
        images = sorted([f for f in input_files if f.suffix.lower() in image_extensions])
        
        if not images:
            return {"success": False, "error": "No valid image files found"}
        
        # Parse parameters
        user_size = parse_size(size)
        duration_list = parse_durations(durations, len(images))
        preset = QUALITY_PRESETS.get(quality, QUALITY_PRESETS['medium'])
        
        # Get target dimensions
        target_width, target_height = get_target_dimensions(images, user_size)
        
        # Process frames
        frames = []
        for img_path in images:
            img = Image.open(img_path)
            
            # Standardize size
            img = standardize_image(img, target_width, target_height)
            
            # Convert to RGB if needed
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Apply color reduction if needed
            if preset['colors'] < 256:
                img = img.convert('P', palette=Image.Palette.ADAPTIVE, colors=preset['colors'])
                img = img.convert('RGB')
            
            frames.append(img)
        
        # Save GIF
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        frames[0].save(
            output_path,
            save_all=True,
            append_images=frames[1:],
            duration=duration_list,
            loop=0,
            optimize=preset['optimize']
        )
        
        # Get file info
        file_size = output_path.stat().st_size
        total_duration = sum(duration_list) / 1000  # in seconds
        
        return {
            "success": True,
            "filename": output_path.name,
            "frames": len(frames),
            "dimensions": f"{target_width}x{target_height}",
            "duration": f"{total_duration:.1f}s",
            "size_bytes": file_size
        }
        
    except Exception as e:
        return {"success": False, "error": str(e)}
