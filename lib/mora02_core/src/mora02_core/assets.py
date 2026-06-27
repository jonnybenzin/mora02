"""Asset dataclass — the unified data structure for any generated artifact.

Replaces the dict-chaos in apps/pilot/comfyui_client.py and elsewhere where
each output had a different shape (sometimes Path, sometimes dict with 'url',
sometimes Frontend-message-blob with 'subtype'). See E5 in the concept doc.
"""

import os
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


# ============================================================================
# Asset references — the wire format that flows through a pipeline
# ============================================================================
# A pipeline step passes a small *reference* string, not the heavy bytes: the
# file stays on disk in its store, only ``asset://<store>/<relpath>`` travels
# between steps. The scheme deliberately carries NO absolute path — a ref names
# a logical *store*, and each container resolves that store to its own mount.
# So the same ref is portable across services (script-runner, pilot, …) that
# mount the shared output tree at different paths. See the Nordstern ADR.

_REF_SCHEME = "asset://"

# Logical store -> default container mount root. Override per container with
# ``MORA02_ASSET_STORE_<STORE>`` (store name uppercased), e.g.
# ``MORA02_ASSET_STORE_COMFYUI=/comfyui-wip``. Defaults match script-runner,
# the executor that runs pipeline steps (ADR-020).
_DEFAULT_STORE_ROOTS = {
    "comfyui": "/comfyui-wip",         # ComfyUI image outputs (read)
    "clipper": "/data/final/clipper",  # assembled video clips (write)
    "gifer": "/data/final/gifer",      # animated GIFs (write)
    "typer": "/data/final/typer",      # text-on-image PNGs (write)
    "tts": "/opt/mora02/output/_default/tts",  # synthesized speech (write)
    "scriptbot": "/data",              # script-runner session workspace
}

# Logical store -> nginx URL *path* (host-less). Single source for both the
# public URL (``url_for_ref``) and the internal root-relative path
# (``path_for_ref``, used to feed an asset back into ComfyUI). The store concept
# owns its serving path here, so a ref resolves by store rather than by guessing
# from the file path (the path-heuristic ``Asset.url``, kept for legacy
# Pilot/comfyui consumers). nginx serves comfyui under /comfyui/wip and the tool
# outputs under /tool-assets/<tool>/ — see docker/nginx-images/nginx.conf.
# Override per container with ``MORA02_ASSET_URLPATH_<STORE>``.
_NGINX_BASE = "http://mora02.local:8092"
_DEFAULT_STORE_URL_PATHS = {
    "comfyui": "/comfyui/wip",
    "clipper": "/tool-assets/clipper",
    "gifer": "/tool-assets/gifer",
    "typer": "/tool-assets/typer",
    "tts": "/tool-assets/tts",
}


class AssetRefError(ValueError):
    """A malformed asset ref, an unknown store, or a containment violation."""


def store_root(store: str) -> Path:
    """Resolve a logical store name to this container's mount root."""
    root = os.environ.get(f"MORA02_ASSET_STORE_{store.upper()}") or _DEFAULT_STORE_ROOTS.get(store)
    if root is None:
        raise AssetRefError(f"unknown asset store {store!r}")
    return Path(root)


def make_ref(store: str, relpath) -> str:
    """Build ``asset://<store>/<relpath>`` from a store + path relative to it."""
    rel = str(relpath).lstrip("/")
    if not store or not rel:
        raise AssetRefError(f"need both store and relpath (got {store!r}, {relpath!r})")
    return f"{_REF_SCHEME}{store}/{rel}"


def parse_ref(ref: str) -> tuple[str, str]:
    """Split a ref into ``(store, relpath)``; raise on a non-ref / malformed input."""
    if not isinstance(ref, str) or not ref.startswith(_REF_SCHEME):
        raise AssetRefError(f"not an asset ref: {ref!r}")
    store, _, rel = ref[len(_REF_SCHEME):].partition("/")
    if not store or not rel:
        raise AssetRefError(f"malformed asset ref: {ref!r}")
    return store, rel


def resolve_ref(ref: str) -> Path:
    """Resolve a ref to a concrete container path, guarding against traversal."""
    store, rel = parse_ref(ref)
    root = store_root(store).resolve()
    path = (root / rel).resolve()
    if path != root and root not in path.parents:
        raise AssetRefError(f"ref escapes its store root: {ref!r}")
    return path


def ref_for_path(path, store: str) -> str:
    """Build a ref for a path that lives in ``store``.

    Uses the path relative to the store root when possible; falls back to the
    bare filename when the path is absolute under a *different* mount than this
    container's (e.g. an Asset built with a host path). Both mounts point at the
    same host directory, so the filename still resolves.
    """
    root = store_root(store).resolve()
    p = Path(path).resolve()
    try:
        rel = p.relative_to(root)
    except ValueError:
        rel = Path(p.name)
    return make_ref(store, str(rel))


def path_for_ref(ref: str) -> str | None:
    """Host-less nginx path for an asset ref (e.g. ``/comfyui/wip/foo.png``).

    Store-aware. Returns ``None`` for a store without a public serving path.
    Used to feed an asset back into ComfyUI (``upload_image_url_to_comfyui``
    downloads a leading-``/`` value from the internal ``nginx-images`` service,
    which is reachable from any container — unlike the public host URL).
    """
    store, rel = parse_ref(ref)
    base = os.environ.get(f"MORA02_ASSET_URLPATH_{store.upper()}") or _DEFAULT_STORE_URL_PATHS.get(store)
    return f"{base.rstrip('/')}/{rel}" if base else None


def url_for_ref(ref: str) -> str:
    """Public nginx URL for an asset ref, resolved via the store's serving path.

    Store-aware (each store knows its nginx serving path) — the correct
    counterpart to the path-heuristic ``Asset.url`` for anything that carries a
    ref, e.g. pipeline steps. Falls back to a ``file://`` path for stores without
    a public serving path.
    """
    path = path_for_ref(ref)
    if path:
        return f"{_NGINX_BASE}{path}"
    store, rel = parse_ref(ref)
    return f"file://{store_root(store)}/{rel}"
