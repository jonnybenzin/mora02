"""Asset dataclass — the unified data structure for any generated artifact.

Replaces the dict-chaos in apps/pilot/comfyui_client.py and elsewhere where
each output had a different shape (sometimes Path, sometimes dict with 'url',
sometimes Frontend-message-blob with 'subtype'). See E5 in the concept doc.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


AssetType = Literal["image", "video", "audio", "text"]


@dataclass
class Asset:
    """A unified representation of a generated artifact.

    The user_id field is multi-user preparation (E7): every library function
    threads it through, even if the value is always 'default' for now.
    """

    id: str
    type: AssetType
    path: Path
    user_id: str = "default"
    metadata: dict = field(default_factory=dict)

    @property
    def url(self) -> str:
        """URL relative to the host's nginx-images mount.

        Heuristic mapping for the standard Mora02 output layout. Apps with
        non-default mounts may compute their own URL instead.
        """
        s = str(self.path)
        if "/output/_default/comfyui/wip/" in s:
            return s.replace(
                "/opt/mora02/output/_default/comfyui/wip/",
                "http://mora02.local:8092/comfyui-wip/",
            )
        if "/output/_default/" in s:
            tail = s.split("/output/_default/", 1)[1]
            return f"http://mora02.local:8092/{tail}"
        return f"file://{s}"

    @property
    def filename(self) -> str:
        return self.path.name
