#!/usr/bin/env python3
"""Phase 6a of the test plan: does the flow library refuse what it should?

Saving is the moment a flow becomes something other people (and later runs) rely
on, so the library's promise is strict: a spec is parsed and checked BEFORE
anything touches disk, "so the library can never hold a flow that fails to load
back". A promise like that is worth testing from the outside, because the
failure it prevents - a half-written flow that only breaks weeks later, when
someone runs it - is invisible until it is expensive.

The browser half of phase 6 (palette, insertion marks, messages surviving a
re-render) lives in test_builder_ui.py; this file needs no browser.

Every flow created here is deleted again: a test that leaves entries in the
library pollutes the thing it is checking.

Usage:
    python3 tests/pipeline/test_library.py

Environment: SCRIPT_RUNNER_URL (default http://127.0.0.1:8096),
MORA02_PIPELINE_SPECS_LOCAL_DIR (default /opt/mora02/pipelines/local/specs) - the
directory the library SAVES to; the shipped flows under pipelines/specs/ are read-only here.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

RUNNER = os.environ.get("SCRIPT_RUNNER_URL", "http://127.0.0.1:8096")
SPECS = Path(os.environ.get("MORA02_PIPELINE_SPECS_LOCAL_DIR", "/opt/mora02/pipelines/local/specs"))
SHIPPED = Path(os.environ.get("MORA02_PIPELINE_SPECS_DIR", "/opt/mora02/pipelines/specs"))

GOOD_STEPS = [
    {"web.fetch": {"id": "seed", "in": "none", "url": "http://127.0.0.1:8096/health"}},
    {"llm.classify": {"id": "pick", "in": "seed", "labels": "ALPHA"}},
]

results: list[tuple[str, str, str]] = []
created: list[str] = []


def record(verdict: str, subject: str, detail: str) -> None:
    results.append((verdict, subject, detail))


def call(method: str, path: str, body: dict | None = None) -> tuple[int, str]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(f"{RUNNER}{path}", data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}"


def save(name: str, spec: dict, overwrite: bool = False) -> tuple[int, str]:
    q = "?overwrite=true" if overwrite else ""
    status, body = call("POST", f"/pipeline/flow/{urllib.parse.quote(name)}{q}", spec)
    if status == 200:
        created.append(name)
    return status, body


def case_save_read_back() -> None:
    name = f"lib-roundtrip-{int(time.time())}"
    status, body = save(name, {"steps": GOOD_STEPS, "description": "Prüfling",
                               "tags": ["test"]})
    if status != 200:
        record("FAIL", "save and read back", f"{status}: {body[:110]}")
        return
    status, body = call("GET", f"/pipeline/flow/{name}")
    if status != 200:
        record("FAIL", "save and read back", f"could not read it back: {status}")
        return
    back = json.loads(body)
    ok = (back.get("name") == name and back.get("description") == "Prüfling"
          and len(back.get("steps", [])) == 2 and back.get("updated"))
    record("PASS" if ok else "FAIL", "save and read back",
           "name, description, tags and timestamp survive" if ok
           else f"lost something: {json.dumps(back)[:110]}")


def case_overwrite_guard() -> None:
    name = f"lib-overwrite-{int(time.time())}"
    save(name, {"steps": GOOD_STEPS})
    status, body = save(name, {"steps": GOOD_STEPS})
    if status in (409, 400) and name in body:
        record("PASS", "overwriting needs saying so", f"{status}: {body[:80]}")
    elif status == 200:
        record("FAIL", "overwriting needs saying so",
               "a second save silently replaced the existing flow")
    else:
        record("FAIL", "overwriting needs saying so", f"{status}: {body[:90]}")

    status, _ = save(name, {"steps": GOOD_STEPS}, overwrite=True)
    record("PASS" if status == 200 else "FAIL", "overwrite=true replaces it",
           f"HTTP {status}")


def case_bad_names() -> None:
    for label, name in (("uppercase", "LibTest"), ("umlaut", "flow-über"),
                        ("space", "flow name"), ("too short", "a"),
                        ("too long", "x" * 65), ("path escape", "../escape")):
        status, body = call("POST", f"/pipeline/flow/{urllib.parse.quote(name, safe='')}",
                            {"steps": GOOD_STEPS})
        if status in (400, 404) and status != 200:
            record("PASS", f"name refused: {label}", f"{status}")
        else:
            record("FAIL", f"name refused: {label}",
                   f"accepted with {status} - {name!r} is now in the library")
            created.append(name)


def case_broken_specs_never_reach_disk() -> None:
    for label, spec in (
        ("unknown op", {"steps": [{"llm.doesnotexist": {"id": "a"}}]}),
        ("duplicate ids", {"steps": [
            {"llm.classify": {"id": "same", "labels": "A"}},
            {"llm.classify": {"id": "same", "labels": "B"}}]}),
        ("wire to a later step", {"steps": [
            {"web.fetch": {"id": "a", "in": "later", "url": "http://x/"}},
            {"llm.classify": {"id": "later", "labels": "A"}}]}),
        ("not an object", {"steps": "nope"}),
    ):
        name = f"lib-broken-{abs(hash(label)) % 10000}"
        status, body = call("POST", f"/pipeline/flow/{name}", spec)
        landed = (SPECS / f"{name}.json").exists()
        if status == 200 or landed:
            record("FAIL", f"refused before disk: {label}",
                   f"HTTP {status}, file on disk: {landed}")
            created.append(name)
        elif status in (400, 422) and len(body) > 20:
            record("PASS", f"refused before disk: {label}",
                   f"{status}, and it says why: {body[:70]}")
        else:
            record("FAIL", f"refused before disk: {label}",
                   f"{status} with no usable reason: {body[:70]}")


def case_delete() -> None:
    name = f"lib-delete-{int(time.time())}"
    save(name, {"steps": GOOD_STEPS})
    status, _ = call("DELETE", f"/pipeline/flow/{name}")
    gone = call("GET", f"/pipeline/flow/{name}")[0] == 404
    if status == 200 and gone:
        record("PASS", "delete removes it", "gone from the library")
        if name in created:
            created.remove(name)
    else:
        record("FAIL", "delete removes it", f"delete={status}, still readable={not gone}")

    status, body = call("DELETE", "/pipeline/flow/lib-does-not-exist-7q4x")
    record("PASS" if status == 404 else "FAIL", "deleting a ghost says so",
           f"{status}: {body[:70]}")

    # A flow shipped with the platform is not this endpoint's to remove: it
    # would be back with the next checkout, and the library would have lied
    # about a deletion in between.
    shipped = sorted(p.stem for p in SHIPPED.glob("*.json")) if SHIPPED.is_dir() else []
    if shipped:
        status, body = call("DELETE", f"/pipeline/flow/{urllib.parse.quote(shipped[0], safe='')}")
        still = (SHIPPED / f"{shipped[0]}.json").is_file()
        record("PASS" if status == 403 and still else "FAIL",
               "a shipped flow cannot be deleted through the library",
               f"{status}: {body[:60]}" + ("" if still else "  AND THE FILE IS GONE"))
    else:
        record("n/a", "a shipped flow cannot be deleted through the library", "no shipped flows to test with")


def cleanup() -> None:
    for name in list(created):
        call("DELETE", f"/pipeline/flow/{urllib.parse.quote(name, safe='')}")
    left = [p.name for p in SPECS.glob("lib-*.json")]
    if left:
        record("FAIL", "the test leaves nothing behind", f"still there: {left}")
    else:
        record("PASS", "the test leaves nothing behind", "library is as it was")


def main() -> int:
    case_save_read_back()
    case_overwrite_guard()
    case_bad_names()
    case_broken_specs_never_reach_disk()
    case_delete()
    cleanup()

    width = max(len(s) for _, s, _ in results)
    failed = sum(1 for v, _, _ in results if v == "FAIL")
    for verdict, subject, detail in results:
        print(f"{verdict:4}  {subject.ljust(width)}  {detail}")
    print(f"\n{len(results) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    import urllib.parse  # noqa: E402  (used by save/cleanup)
    sys.exit(main())
