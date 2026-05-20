"""Central environment configuration loader.

All Mora02 services share the same .env file at /opt/mora02/docker/.env.
This module reads it at import-time (without overwriting already-set vars),
then exposes helpers to fetch values fail-fast or with a default.

Usage:
    from mora02_core import auth
    token = auth.require("BASEROW_TOKEN")
    url = auth.get("BASEROW_URL", "http://baserow:80")
"""

import os
from pathlib import Path


_ENV_FILE = Path("/opt/mora02/docker/.env")


def _load_env_file(path: Path) -> None:
    """Parse a .env file and merge into os.environ without overwriting."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


_load_env_file(_ENV_FILE)


def require(key: str) -> str:
    """Return the env value or raise RuntimeError with a clear message.

    Use this at the call site where the secret is actually consumed, not at
    module top-level — that way an app that doesn't need a specific key won't
    fail to import.
    """
    val = os.environ.get(key)
    if not val:
        raise RuntimeError(
            f"Environment variable {key!r} is required by mora02_core "
            f"but not set. Check {_ENV_FILE} or your container env."
        )
    return val


def get(key: str, default: str = "") -> str:
    """Return the env value or the given default."""
    return os.environ.get(key, default)
