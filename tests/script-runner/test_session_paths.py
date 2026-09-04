#!/usr/bin/env python3
"""Can a request name a directory that is not a session?

`get_session_dir` resolves the path for all nine session endpoints, two of which
hand the result to `shutil.rmtree`. Review run 3 (2026-09-04) found that it
checked only `.exists()`, so a percent-encoded `..` walked out of the session
directory and the delete emptied the whole data mount — which carries, by bind
mount, the flow library, every run log and run bucket, the agent definitions and
the gateway's workspace. The Pilot forwards `/sr/<path>` verbatim and listens on
every interface, so that was reachable from the house network with no credential.

What this suite pins down:

  * the encoded forms of `..` really do reach a path parameter (they do; this is
    not theory, it is why the bug existed)
  * a name that is not a session id is refused, and NOTHING is deleted
  * a real session still deletes, and only itself
  * a FILE with an id-shaped name is 404, not a half-finished rmtree

Offline and free: builds its own data directory under /tmp, touches nothing real.

Usage:
    PYTHONPATH=lib/mora02_core/src:apps/script-runner/app \\
        python3 tests/script-runner/test_session_paths.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib" / "mora02_core" / "src"))
sys.path.insert(0, str(ROOT / "apps" / "script-runner" / "app"))

# main.py builds a multipart route at import time. python-multipart is a
# dependency of the container image, not of this machine's python; a stub gets
# the module imported without it. Nothing under test touches file uploads.
_mp = types.ModuleType("python_multipart")
_mp.__version__ = "0.0.20"
_sub = types.ModuleType("python_multipart.multipart")
for _n in ("MultiPartParser", "QuerystringParser", "FormParser", "MultipartPart",
           "File", "Field"):
    setattr(_sub, _n, type(_n, (), {}))
_sub.parse_options_header = lambda *a, **k: (b"", {})
_mp.multipart = _sub
sys.modules.setdefault("python_multipart", _mp)
sys.modules.setdefault("python_multipart.multipart", _sub)

# The data mount, pointed somewhere disposable BEFORE main.py is imported: it
# creates its directory tree at import time.
DATA = Path(tempfile.mkdtemp(prefix="sr-session-"))
import os  # noqa: E402

os.environ["MORA02_SCRIPT_RUNNER_DATA"] = str(DATA)

import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

results: list[tuple[str, str, str]] = []


def record(ok: bool, subject: str, detail: str = "") -> None:
    results.append(("PASS" if ok else "FAIL", subject, detail))
    print(f"[{'  ok  ' if ok else ' FAIL '}] {subject}{(': ' + detail) if detail else ''}")


def main_() -> int:
    client = TestClient(main.app)
    wip = main.WIP_DIR

    # A neighbour of the session directory, standing in for everything the data
    # mount really carries: the flow library, the run logs, the agent folders.
    treasure = DATA / "pipelines"
    (treasure / "specs").mkdir(parents=True, exist_ok=True)
    (treasure / "specs" / "tanzbaer.json").write_text('{"name": "tanzbaer"}')

    # --- the encoded forms reach the parameter -----------------------------
    seen: list[str] = []
    from fastapi import FastAPI
    spy = FastAPI()

    @spy.delete("/session/{session_id}")
    async def _spy(session_id: str):
        seen.append(session_id)
        return {"got": session_id}

    with TestClient(spy) as c2:
        c2.delete("/session/%2e%2e")
    record(seen == [".."],
           "a percent-encoded dot-dot really does arrive as a path parameter",
           repr(seen[0]) if seen else "nothing arrived")

    # --- what must be refused ----------------------------------------------
    # Two layers may refuse: the router, when the decoded name matches no route
    # at all, and the guard, when it matches but is not an id. Either is a
    # refusal — what matters is that nothing is deleted and 200 never happens.
    for bad, why in [("%2e%2e", "the encoded dot-dot that caused this"),
                     ("%2e%2e%2f%2e%2e", "two of them, with a slash"),
                     ("wip", "a plain word"),
                     ("2609041724_ZZZZZZ", "id-shaped but not hex"),
                     ("2609041724_a1b2c3x", "one character too long"),
                     ("..%2f..", "a slash in the middle"),
                     ("", "nothing at all")]:
        r = client.delete(f"/session/{bad}")
        by = {422: "the guard", 404: "the router or a missing session"}.get(r.status_code, "?")
        record(r.status_code in (404, 422), f"refused: {why}", f"HTTP {r.status_code} ({by})")

    record(treasure.is_dir() and (treasure / "specs" / "tanzbaer.json").is_file(),
           "after every refusal the neighbouring data is untouched",
           f"{len(list(DATA.iterdir()))} entries still in the data directory")

    # --- what must still work ----------------------------------------------
    sid = main.create_session()
    record(main.get_session_dir(sid).is_dir(), "a session created here resolves", sid)
    (wip / sid / "input" / "a.txt").write_text("x")

    other = main.create_session()
    r = client.delete(f"/session/{sid}")
    record(r.status_code == 200, "a real session deletes", f"HTTP {r.status_code}")
    record(not (wip / sid).exists(), "and its directory is gone")
    record((wip / other).is_dir(), "while the session beside it is not touched")
    record(treasure.is_dir(), "and neither is anything outside the session directory")

    r = client.delete(f"/session/{sid}")
    record(r.status_code == 404, "deleting it twice is a 404", f"HTTP {r.status_code}")

    # --- a file wearing an id's name ---------------------------------------
    (wip / "2609041724_abcdef").write_text("not a directory")
    r = client.delete("/session/2609041724_abcdef")
    record(r.status_code == 404, "a FILE with an id-shaped name is 404, not a failed rmtree",
           f"HTTP {r.status_code}")
    record((wip / "2609041724_abcdef").is_file(), "and it is still there")

    # --- a symlink out of the tree -----------------------------------------
    # The pattern above cannot see a symlink; the containment check can.
    link = wip / "2609041725_abcdef"
    try:
        link.symlink_to(treasure, target_is_directory=True)
    except OSError:
        record(True, "symlink case skipped (not permitted here)")
    else:
        r = client.delete(f"/session/{link.name}")
        record(r.status_code == 422, "a session that is a symlink out of the tree is refused",
               f"HTTP {r.status_code}")
        record(treasure.is_dir() and (treasure / "specs" / "tanzbaer.json").is_file(),
               "and what it pointed at survived")

    fails = [r for r in results if r[0] == "FAIL"]
    print(f"\n{len(results) - len(fails)} passed, {len(fails)} failed")
    for _, s, d in fails:
        print(f"  FAILED  {s}: {d}")
    return 1 if fails else 0


if __name__ == "__main__":
    try:
        sys.exit(main_())
    finally:
        shutil.rmtree(DATA, ignore_errors=True)
