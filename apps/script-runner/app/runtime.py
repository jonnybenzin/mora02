"""What every part of the script-runner stands on: where things live, and the
rules for turning a caller's text into a path.

Split out of main.py in September 2026. That file had grown to 3400 lines
holding six unrelated subsystems, and this is the piece all of them share —
which is why it comes out first: a module that both the media service and the
pipeline import cannot live in either of them.

The pattern is the one already used in this directory: agents.py and
mcp_tools.py are routers that main.py includes. These are not routes at all,
just the ground they stand on.
"""

from __future__ import annotations

import asyncio
from functools import partial
import mimetypes
import os
import re
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, List

from fastapi import HTTPException

from mora02_core import auth
from mora02_core._common import get_logger, segment_problem
from mora02_core import assets as asset_refs
from mora02_core.db import api as db_api
from mora02_core.pipeline import runlog as pipeline_runlog

_log = get_logger("script-runner")

# ==========================================================================
# CONFIG
# ==========================================================================

_log = get_logger("script-runner")

# The mount the media service works in. Overridable so the file can be imported
# outside the container -- a test cannot create /data, and until it could be
# pointed elsewhere there was no way to test any of this without a container.
# One version, and it is the one /health reports. The FastAPI object said
# 1.2.0 while /health and / said 1.4.0, so whoever bumped one left the other
# behind and a reader could not tell which was authoritative (review 3).
SERVICE_VERSION = "1.4.0"

DATA_DIR = Path(os.environ.get("MORA02_SCRIPT_RUNNER_DATA", "/data"))
WIP_DIR = DATA_DIR / "wip"
FINAL_DIR = DATA_DIR / "final"

# Path mapping (container → host)
CONTAINER_DATA_PATH = "/data"
HOST_DATA_PATH = "/opt/mora02/output/_default/script-bot"

# nginx-images URL for assets
NGINX_BASE_URL = "http://mora02.local:8092/script-bot-assets"

# Stock photo APIs — keys via central env loader (mora02_core.auth)
PEXELS_API_KEY = auth.get("PEXELS_API_KEY", "")
PIXABAY_API_KEY = auth.get("PIXABAY_API_KEY", "")

# Ensure directories exist
for d in [WIP_DIR, FINAL_DIR, FINAL_DIR / "gifer", FINAL_DIR / "clipper", FINAL_DIR / "typer", FINAL_DIR / "pexels", FINAL_DIR / "pixabay"]:
    d.mkdir(parents=True, exist_ok=True)



def create_session() -> str:
    """Create new session with unique ID"""
    session_id = datetime.now().strftime("%y%m%d%H%M") + "_" + uuid.uuid4().hex[:6]
    session_dir = WIP_DIR / session_id
    (session_dir / "input").mkdir(parents=True, exist_ok=True)
    (session_dir / "output").mkdir(parents=True, exist_ok=True)
    return session_id

# A session id is what create_session() makes: a timestamp, an underscore and six
# hex characters. Checked rather than trusted, because this one function resolves
# the path for all nine callers -- two of which hand it to shutil.rmtree.
#
# MEASURED 2026-09-04: `DELETE /session/%2e%2e` arrives here with session_id ".."
# (uvicorn percent-decodes before routing; a literal ".." is normalised away by
# clients, the encoded form is not). `Path("/data/wip/..").exists()` is true, so
# the old check passed it straight through and rmtree emptied /data -- which
# carries, by bind mount, the flow library, every run log and run bucket, the
# agent definitions and the gateway's workspace. The Pilot forwards /sr/<path>
# to this service verbatim and listens on every interface, so that was reachable
# from the house network without any credential.
_SESSION_ID_RE = re.compile(r"^[0-9]{10}_[0-9a-f]{6}$")

# A flow name is a file name under pipelines/specs/. The rule lives in the
# library since the MCP door started saving flows too (September 2026); this
# name stays for the routes that import it from here.
from mora02_core.pipeline.spec import FLOW_NAME_RE as _FLOW_NAME_RE  # noqa: E402,F401


# The rule itself lives in mora02_core._common, because the library turns
# caller-supplied text into file names too (a run id is one). One rule, two
# users, no second copy to drift.
_segment_problem = segment_problem


def _media_type(suffix: str) -> str:
    """The MIME type a browser needs to play a file inline.

    Four file-serving endpoints each carried their own table and they had
    already drifted: `.webm` was missing from one, `.webp` from two, so the same
    clip played inline through one route and downloaded as a blob through
    another (review 3, 2026-09-04). The standard library knows these; the
    fallback stays the same.
    """
    guess, _ = mimetypes.guess_type(f"x{suffix}")
    return guess or "application/octet-stream"


def safe_segment(value: Any, what: str) -> str:
    """One path segment, from an HTTP caller. 422 for anything that is not a name.

    Review 3 (2026-09-04) found six endpoints and five step handlers building a
    path out of a request field and then WRITING to it. That is reachable
    without a credential: apps/pilot/app.py forwards /sr/<path> to this service
    verbatim and listens on every interface. And the container writes into
    /opt/mora02/pipelines (the flow library and every run log), /opt/mora02/agents
    (what an agent may hold) and /llm-switch, whose mailbox a root unit on the
    HOST consumes -- so a free choice of path does not stay in the container.

    Permissive about what a name may contain -- a real filename has spaces and
    brackets in it -- and airtight about what makes it a path: no separator, no
    `.` or `..`, nothing empty.
    """
    problem = _segment_problem(value)
    if problem:
        raise HTTPException(status_code=422,
                            detail=f"{what}: {str(value)[:80]!r} {problem}")
    return str(value)


def step_segment(value: Any, what: str) -> str:
    """The same rule inside a pipeline step. ValueError rather than
    HTTPException, so the step endpoint's funnel records it as a failed STEP in
    the run log instead of raising past it."""
    problem = _segment_problem(value)
    if problem:
        raise ValueError(f"{what}: {str(value)[:80]!r} {problem}")
    return str(value)


def step_out_path(store: str, name: Any, default: str) -> Path:
    """Where a step writes its output: the caller's name, or a generated one.

    Four handlers built this by hand as `store_root(store) / params["name"]`,
    and `name` is a declared vocabulary parameter that `validate_op` puts no
    pattern on -- so a compiled flow, whose params a model may have composed,
    chose the write path (review 3, 2026-09-04). One helper so a fifth handler
    cannot forget.
    """
    root = asset_refs.store_root(store)
    out_name = step_segment(name, "name") if name else default
    path = root / out_name
    try:
        path.resolve().relative_to(root.resolve())
    except (ValueError, OSError):
        raise ValueError(f"name: {out_name!r} points outside store {store!r}")
    return path


def inside(root: Path, candidate: Path, what: str) -> Path:
    """``candidate``, proven to resolve inside ``root``. The net under
    safe_segment: a pattern cannot see a symlink, this can."""
    try:
        candidate.resolve().relative_to(root.resolve())
    except (ValueError, OSError):
        raise HTTPException(status_code=422, detail=f"{what} points outside {root}")
    return candidate


async def _docker_cli(*argv: str, timeout: int) -> subprocess.CompletedProcess:
    """One `docker` command, in a thread.

    `docker start chatterbox-tts` can legitimately take most of its minute while
    the container warms its model up, and `status` is polled by a UI panel. On
    the event loop each of those stopped the whole service -- health checks,
    pipeline steps, an agent's tool calls (review 3, 2026-09-04).
    """
    return await asyncio.to_thread(
        partial(subprocess.run, list(argv), capture_output=True, text=True,
                timeout=timeout)
    )


def _checked_run_id(run_id: str, what: str = "run_id") -> str:
    """A run id from a caller, refused as a 422 rather than a 500.

    The library refuses one that cannot name a log file; three endpoints take
    one straight from a request, and before review 3 they handed it through
    unchecked -- `/pipeline/rerun`, `/pipeline/rerun-plan` and `/pipeline/replay`
    would read any .jsonl or .json the container can see.
    """
    try:
        return pipeline_runlog.check_run_id(run_id)
    except pipeline_runlog.BadRunId as e:
        raise HTTPException(status_code=422, detail=f"{what}: {e}")


def get_session_dir(session_id: str) -> Path:
    """The directory of one session. Raises 422 for anything that is not an id,
    404 for an id with no directory."""
    if not _SESSION_ID_RE.match(session_id or ""):
        raise HTTPException(
            status_code=422,
            detail=f"{session_id!r} is not a session id (ten digits, an "
                   f"underscore, six hex characters)",
        )
    session_dir = WIP_DIR / session_id
    # Second net, and not redundant: the pattern above cannot see a symlink.
    # Whatever the name resolves to has to sit inside the wip directory.
    try:
        session_dir.resolve().relative_to(WIP_DIR.resolve())
    except (ValueError, OSError):
        raise HTTPException(status_code=422, detail=f"session {session_id} is not inside the session directory")
    # is_dir, not exists: a FILE of that name would pass exists() and then fail
    # inside rmtree, after the caller had been told the session was found.
    if not session_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return session_dir

def create_timestamp() -> str:
    """Create timestamp for filenames — format: YYMMDD-HHMM"""
    return datetime.now().strftime("%y%m%d-%H%M")

def container_to_host_path(container_path: str) -> str:
    """Convert container path to host path"""
    return container_path.replace(CONTAINER_DATA_PATH, HOST_DATA_PATH)

def get_nginx_url(script_type: str, folder: str, filename: str) -> str:
    """Get nginx URL for asset"""
    return f"{NGINX_BASE_URL}/{script_type}/{folder}/{filename}"

async def create_baserow_entry(script_type: str, folder: str, files: List[str], host_path: str):
    """Create entry in Baserow sb_assets table via mora02_core.db.api."""
    try:
        first_file = files[0] if files else ""
        data = {
            "type": script_type,
            "path": host_path,
            "filename": ", ".join(files),
            "files_count": len(files),
            "preview_url": get_nginx_url(script_type, folder, first_file),
            "created": datetime.now().isoformat(),
        }
        return await db_api.insert("sb_assets", data)
    except Exception as e:
        # Deliberately swallowed, and the only place in this file where that is
        # right: this is a record ABOUT a finished media job, not part of it.
        # A database that is down must not lose the clip that was just made.
        _log.warning("baserow insert failed: %s", e)
        return None
