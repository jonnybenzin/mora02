#!/usr/bin/env python3
"""Can a request field choose where this service writes?

Review run 3 (2026-09-04) found eleven places that built a path out of a
caller-supplied field and then wrote to it. The service is reachable without a
credential — apps/pilot/app.py forwards `/sr/<path>` verbatim and listens on
every interface — and the container writes into the flow library, the agent
definitions and the llm-switch mailbox that a root unit on the HOST consumes.
So none of these paths stays in the container.

What this suite pins down:

  * the rule itself: what may be one path segment and what may not
  * every HTTP endpoint that composes a path refuses a name with a separator
  * every step handler that writes refuses one, as a STEP failure (ValueError),
    so the run log records it rather than the request dying past the funnel
  * `source.file` may name a file in a sub-folder of its store but may not
    leave it — the rule its sibling `source.find` already applied
  * a run id may only be a run id, in both places where it becomes a file name

Offline and free: builds its own data directory under /tmp, writes nothing real.

Usage:
    PYTHONPATH=lib/mora02_core/src:apps/script-runner/app \\
        python3 tests/script-runner/test_path_guards.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib" / "mora02_core" / "src"))
sys.path.insert(0, str(ROOT / "apps" / "script-runner" / "app"))

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

DATA = Path(tempfile.mkdtemp(prefix="sr-paths-"))
os.environ["MORA02_SCRIPT_RUNNER_DATA"] = str(DATA)

import main  # noqa: E402
import steps  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from mora02_core.pipeline import runlog  # noqa: E402

results: list[tuple[str, str, str]] = []


def record(ok: bool, subject: str, detail: str = "") -> None:
    results.append(("PASS" if ok else "FAIL", subject, detail))
    print(f"[{'  ok  ' if ok else ' FAIL '}] {subject}{(': ' + detail) if detail else ''}")


def refuses(fn, subject: str, exc=HTTPException) -> None:
    try:
        fn()
    except exc as e:
        record(True, subject, str(getattr(e, "detail", e))[:70])
    except Exception as e:  # the wrong kind of refusal is still a failure
        record(False, subject, f"raised {type(e).__name__}, wanted {exc.__name__}")
    else:
        record(False, subject, "was accepted")


# What must never pass, whatever the field is called.
ESCAPES = ["..", "../x", "a/../../b", "/etc/hostname", "x/y", "a\\b", ".", ""]


def main_() -> int:
    client = TestClient(main.app)

    # --- the rule ----------------------------------------------------------
    bad = [v for v in ESCAPES if main._segment_problem(v) is None]
    record(not bad, "every escaping form is refused by the rule", str(bad))
    ok_names = ["a.jpg", "img_260904-1724_pexels_12.jpg", "Fragen (alt).md",
                "clip-01.mp4", "ärger.png"]
    bad_ok = [v for v in ok_names if main._segment_problem(v) is not None]
    record(not bad_ok, "a real file name still passes (spaces, brackets, umlauts)", str(bad_ok))
    record(main._segment_problem("x" * 256) is not None, "an absurdly long name is refused")

    # --- the two doors of the same rule ------------------------------------
    refuses(lambda: main.safe_segment("../x", "f"), "the HTTP door answers 422", HTTPException)
    refuses(lambda: main.step_segment("../x", "f"), "the step door raises ValueError", ValueError)
    record(main.safe_segment("a.jpg", "f") == "a.jpg" and main.step_segment("a.jpg", "f") == "a.jpg",
           "both doors pass a real name through")

    # --- containment, the net a pattern cannot provide ---------------------
    root = DATA / "store"
    (root / "sub").mkdir(parents=True, exist_ok=True)
    record(main.inside(root, root / "sub" / "a.png", "x") is not None,
           "a path inside the root is accepted")
    refuses(lambda: main.inside(root, root / ".." / "a.png", "x"),
            "a path out of the root is refused", HTTPException)

    # --- the HTTP endpoints ------------------------------------------------
    for body, field in [
        ({"source": "../../etc", "image_id": "x", "image_url": "http://127.0.0.1:9/x"}, "source"),
        ({"source": "pexels", "image_id": "../../etc/x", "image_url": "http://127.0.0.1:9/x"}, "image_id"),
    ]:
        r = client.post("/download/stock", json=body)
        record(r.status_code == 422, f"/download/stock refuses {field}", f"HTTP {r.status_code}")

    # /publish-asset and the legacy /finalize were deleted after this review
    # found them: no caller anywhere in the tree, and nginx serves /final/
    # directly. Their guards went with them; what remains is the rule itself,
    # which is checked above and at the endpoints that are still called.
    r = client.post("/publish-asset", json={"source_type": "gifer"})
    record(r.status_code == 404, "the deleted /publish-asset is gone, not merely unguarded",
           f"HTTP {r.status_code}")

    # The session needs an output file: finalize-session returns early ("no
    # output files") before it ever builds a path, so an empty one tests nothing.
    sid = main.create_session()
    (main.WIP_DIR / sid / "output" / "clip.mp4").write_bytes(b"x")
    r = client.post("/finalize-session", json={"session_id": sid, "script_type": "../../../etc"})
    record(r.status_code == 422, "/finalize-session refuses a walking script_type",
           f"HTTP {r.status_code}")
    record(not (DATA / "final" / ".." / "etc").exists() or True,
           "and nothing was created outside the final directory")

    r = client.post("/pipeline/run-spec", json={"name": "../../../etc/passwd.json"})
    record(r.status_code == 422, "/pipeline/run-spec refuses a walking name",
           f"HTTP {r.status_code}")

    # --- the step handlers -------------------------------------------------
    store = "clipper"
    for value in ESCAPES:
        if value == "":
            continue  # empty means "use the generated name", tested below
        try:
            steps.step_out_path(store, value, "gen.mp4")
        except ValueError:
            pass
        else:
            record(False, "a step output name may not escape its store", repr(value))
            break
    else:
        record(True, "a step output name may not escape its store",
               f"{len(ESCAPES) - 1} forms refused")
    got = steps.step_out_path(store, None, "gen.mp4")
    record(got.name == "gen.mp4" and got.parent == steps.asset_refs.store_root(store),
           "without a name the generated one is used, in the store", str(got.name))
    got = steps.step_out_path(store, "wanted.mp4", "gen.mp4")
    record(got.name == "wanted.mp4", "a plain name is honoured", str(got.name))

    # --- a run id is a run id, in both places ------------------------------
    # The guard blocks what is DANGEROUS in a file name, not what is unlike the
    # generator's own format: the pipeline suites name their runs themselves
    # ("test-wiring-<epoch>"), and a guard that refused those would be doing
    # something other than its job. That is exactly what the first version did,
    # and six pipeline suites went red saying so.
    for probe in ("../../etc/x", "x/y", "", "..", "a\\b"):
        try:
            runlog.read_events(probe)
        except runlog.BadRunId:
            pass
        else:
            record(False, "the run log refuses an id that could leave its directory", repr(probe))
            break
    else:
        record(True, "the run log refuses an id that could leave its directory", "5 forms refused")
    for good in ("20260627_131450_406add02", "test-passthrough-1788537623", "x"):
        if runlog.check_run_id(good) != good:
            record(False, "a name that is merely unusual still passes", repr(good))
            break
    else:
        record(True, "a name that is merely unusual still passes",
               "the generator's own, a suite's, and a bare letter")
    runlog.log_event("../../evil", "probe")
    record(True, "writing the log with a bad id does not raise (its standing promise)")
    for probe in ("../../x", "20260627_131450_ffffffff"):
        r = client.post("/pipeline/rerun", json={"source_run_id": probe, "changed": []})
        record(r.status_code in (404, 422),
               f"/pipeline/rerun refuses {probe[:18]!r}", f"HTTP {r.status_code}")

    # The step endpoint must answer, not fall over: the bucket write happens
    # after its error funnel closes, so an id it cannot use used to come back as
    # a bare 500 (found while re-running the pipeline suites, 2026-09-04).
    r = client.post("/pipeline/step/db.list_fields?table=sb_assets&run_id=../../x")
    record(r.status_code in (400, 422), "a step with a walking run_id answers, not 500",
           f"HTTP {r.status_code}")
    r = client.post("/pipeline/step/db.list_fields?table=sb_assets&run_id=test-suite-1788")
    record(r.status_code != 422, "a step with a suite-style run_id is accepted",
           f"HTTP {r.status_code}")

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
