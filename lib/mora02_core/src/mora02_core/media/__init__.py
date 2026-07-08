"""mora02_core.media — pure Python media operations (gifer, typer, clipper).

Migrated from apps/script-runner/app/scripts/ per ADR-018. Each function
returns an Asset on success and raises MediaError on failure.

Recommended for new code:

    from mora02_core.media import create_gif, create_text_frame, create_clip

    asset = create_gif(input_files, output_path, durations="1,2,2,4")
    # asset is an mora02_core.assets.Asset
"""

from mora02_core.media import tts
from mora02_core.media._errors import MediaError
from mora02_core.media.gifer import create_gif
from mora02_core.media.typer import create_text_frame
from mora02_core.media.clipper import create_clip, mux_audio
from mora02_core.media.frames import extract_frame

__all__ = [
    "MediaError",
    "create_gif",
    "create_text_frame",
    "create_clip",
    "mux_audio",
    "extract_frame",
    "tts",
]
