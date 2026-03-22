# Mora02 Clipper v3.2 — Animated Video Creation Tool  
A command-line tool for generating high-quality animated videos with smooth transitions, parallax effects, and overlays. It runs on Ubuntu 24.04 with an RTX 5090 and uses ffmpeg for encoding. Designed for batch processing of images and videos with customizable animation types and resolution presets.

## Quick Start  
To generate a 1080p animated video from a folder of images:  
```bash
cd /opt/mora02/output/_default/clipper  
python3 clipper.py  
```  
The tool will prompt for input directory, resolution, animation type, and other parameters. It creates a final `.mp4` file in the archive directory with a timestamp.

## What Clipper Does  
Clipper generates smooth 30fps animations with ease-in/ease-out transitions. It supports:  
- **Pan animations** (360° rotation with direction and intensity)  
- **Zoom animations** (in/out with focus point)  
- **Parallax layers** (bg/mg/fg with speed multipliers)  
- **Overlays** (image sequences with scaling, positioning, and looping)  
- **Transitions** between clips (fade or hard cuts)  
- **Audio embedding** from external files  

The output is encoded with libx264 at CRF 18 for high quality and uses ffmpeg's `zoompan` filter for smooth motion.

## Parameters  
All parameters are parsed from user input during execution. Default values are defined in the script:  

| Parameter | Default | Description |
|---------|---------|-------------|
| `width` | 1920 | Width of output video (supports resolution presets like '1080p', '4k', etc.) |
| `height` | 1080 | Height of output video |
| `fps` | 30 | Frame rate for animation |
| `CRF_QUALITY` | 18 | Quality setting for libx264 (lower = better quality) |
| `PRESET` | 'slow' | Encoding speed/quality tradeoff (slower = better quality) |
| `DEFAULT_DURATION` | 4.0 | Default duration for image-based clips |
| `DEFAULT_TRANSITION` | 1.0 | Default duration for transitions between clips |
| `PARALLAX_SPEEDS` | {'bg': 0.3, 'mg': 0.6, 'fg': 1.0} | Speed multipliers for parallax layers |

## Practical Examples  
1. **Creating a LinkedIn post video**  
   Use `linkedin` resolution (1200x627) with a `zoom_in` animation and a 2.0s transition between clips. Overlay a logo in the bottom-right corner with a 1.5x scale.  

2. **Generating a 4K slideshow**  
   Use `4k` resolution and `pan` animations with 90° direction and 30% intensity. Enable parallax layers with `bg` and `fg` for depth.  

3. **Preparing a video for Instagram Reels**  
   Use `reels` resolution (1080x1920) with `zoom_out` animation. Add a 1.0s transition between clips and embed an audio file for background music.  

## How It Works  
1. **Input Processing**  
   The tool scans the `source` directory for images and videos, sorting them by filename. It supports natural sorting (e.g., `img1.png`, `img2.png` → `img10.png`).  

2. **Clip Generation**  
   Each image or video is converted to the target resolution and frame rate. Animation filters are applied using ffmpeg's `zoompan` and `scale` filters.  

3. **Concatenation**  
   Clips are concatenated with transitions using ffmpeg's `xfade` filter. Hard cuts are used if transition duration is 0.  

4. **Overlays and Parallax**  
   Overlay sequences (e.g., `overlay/1.png`, `overlay/2.png`) are applied with scaling and positioning. Parallax layers (bg/mg/fg) are animated with speed multipliers.  

5. **Audio Embedding**  
   An external audio file is embedded using ffmpeg's `aac` encoder.  

6. **Archiving**  
   All source files, overlays, and parallax layers are copied to an archive directory with a timestamp.  

## Directory Structure  
```
/opt/mora02/output/_default/clipper  
├── source/  
│   ├── image1.jpg  
│   ├── image2.jpg  
│   └── overlay/  
│       ├── 1.png  
│       └── 2.png  
├── archive/  
│   ├── 202504151234_clipper/  
│   │   ├── source/  
│   │   │   ├── image1.jpg  
│   │   │   └── overlay/  
│   │   │       ├── 1.png  
│   │   │       └── 2.png  
│   │   └── output.mp4  
│   └── logs/  
│       └── 202504151234_logs.md  
```

## Integration  
- **Pexels**  
  Use Pexels to fetch high-resolution images, then run Clipper to generate animated videos.  

- **Typer**  
  Typer can be used to generate text overlays, which are then applied using the `apply_overlay` function.  

- **Gifer**  
  Gifer can generate animated GIFs, which are then converted to MP4 using Clipper's `prepare_video_clip` function.  

- **Script-Runner**  
  Script-Runner can automate the entire process, calling Clipper with predefined parameters for batch processing.  

## Dependencies & Configuration  
- **ffmpeg**  
  Must be installed and available in the system PATH.  

- **Python 3.10+**  
  Required for running the script.  

- **Configuration Variables**  
  Modify the following in the script:  
  - `BASE_DIR`: Base output directory  
  - `ARCHIVE_BASE`: Directory for archived files  
  - `CRF_QUALITY`: Quality setting for libx264  
  - `PRESET`: Encoding speed/quality tradeoff (e.g., 'slow', 'medium', 'fast')  

## Troubleshooting  
1. **Missing ffmpeg**  
   If `check_ffmpeg()` fails, ensure ffmpeg is installed and in the PATH.  

2. **No media files found**  
   The script scans the `source` directory for images and videos. Ensure files are named with numeric prefixes (e.g., `img1.jpg`, `video1.mp4`).  

3. **Overlay or parallax not applied**  
   Check that overlay files are named sequentially (e.g., `1.png`, `2.png`) and that parallax directories (`bg`, `mg`, `fg`) contain valid image sequences.  

4. **High memory usage**  
   Large 4K videos or long animations may require more memory. Use `--no-parallax` or `--no-overlay` to reduce resource usage.