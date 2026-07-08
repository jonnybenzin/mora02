"""mora02_core.media.frames — pull a still frame out of a video (ffmpeg).

Backs the ``video.last_frame`` pipeline op, which chains image-to-video generation:
each new i2v video starts from the previous video's final frame, so a continuous
motion sequence can be grown one clip at a time.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from mora02_core.media._errors import MediaError


def extract_frame(video_path, out_path, position: str = "last") -> Path:
    """Write one frame of a video to ``out_path`` as an image (PNG).

    ``position``: ``"last"`` (the final frame) or ``"first"``. For the last frame we
    decode the tail of the clip and let ``-update`` overwrite, so the file ends up as
    the last decoded frame — robust across containers without needing the frame count.
    """
    video_path = str(video_path)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if position == "first":
        cmd = ["ffmpeg", "-y", "-i", video_path, "-frames:v", "1", "-q:v", "2", str(out_path)]
    else:
        cmd = ["ffmpeg", "-y", "-sseof", "-3", "-i", video_path,
               "-update", "1", "-q:v", "2", str(out_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not out_path.is_file():
        raise MediaError(f"frame extraction failed: {proc.stderr[-300:]}")
    return out_path
