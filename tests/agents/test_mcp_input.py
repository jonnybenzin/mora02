#!/usr/bin/env python3
"""Does the MCP surface survive what a language model actually sends?

Every argument on this surface is written by a model, not by a caller who read
the schema. Review run 2 (2026-09-04) found four ways that ended in an HTTP 500
instead of a tool result: a number where a string was expected, a url carrying
a control character, a batch element that is not an object, and a spec file
that parses to a list. A model that gets a broken tool invents an answer, so
"the call failed" is never a harmless outcome here.

What this suite pins down:

  * a field is read as text whatever the model put there, and never raises
  * a page that cannot be fetched is reported as that page's error, for EVERY
    way a fetch can fail -- httpx.InvalidURL is not an httpx.HTTPError
  * `note` and `verify` accept a batch with wrong types without losing the
    items beside them, and without recording half of it behind a 500
  * a JSON-RPC batch with a scalar in it still answers the valid messages

Offline and free: no network, no gateway, no model. Fetches are stubbed.

Usage:
    PYTHONPATH=lib/mora02_core/src:apps/script-runner/app python3 tests/agents/test_mcp_input.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib" / "mora02_core" / "src"))
sys.path.insert(0, str(ROOT / "apps" / "script-runner" / "app"))

import httpx  # noqa: E402

import mcp_tools as M  # noqa: E402
from mora02_core import web  # noqa: E402

results: list[tuple[str, str, str]] = []


def record(ok: bool, subject: str, detail: str = "") -> None:
    results.append(("PASS" if ok else "FAIL", subject, detail))
    print(f"[{'  ok  ' if ok else ' FAIL '}] {subject}{(': ' + detail) if detail else ''}")


def call(name: str, args: dict) -> dict:
    """One tool call, as _dispatch would make it. Returns the tool's own dict."""
    return asyncio.run(M._call(name, args))


def main() -> int:
    M.begin_turn({}, session="agent:probe:1")

    # --- a field is text, whatever arrived --------------------------------
    cases = [({"c": "  x  "}, "x"), ({"c": 42}, "42"), ({"c": 3.5}, "3.5"),
             ({"c": ["a"]}, ""), ({"c": {"a": 1}}, ""), ({"c": None}, ""),
             ({"c": True}, ""), ({}, "")]
    bad = [(a, M._text(a, "c"), want) for a, want in cases if M._text(a, "c") != want]
    record(not bad, "a field is read as text for every type a model can send", str(bad)[:80])

    # --- a page that cannot be fetched is that page's error ----------------
    async def stub(kind):
        async def fetch(u, max_chars=None):
            if "bad" in u:
                raise kind
            return {"url": u, "text": "fine", "chars": 4}
        return fetch

    for kind, label in ((httpx.InvalidURL("tab in url"), "httpx.InvalidURL (not an HTTPError)"),
                        (web.WebError("timeout"), "web.WebError"),
                        (RuntimeError("something else"), "an exception nobody predicted")):
        real = web.fetch
        web.fetch = asyncio.run(stub(kind))
        try:
            M._SPENT["pages"] = 0
            out = call("web_read", {"urls": ["https://good.example/", "https://bad.example/"]})
        finally:
            web.fetch = real
        pages = out.get("pages") or []
        ok = (len(pages) == 2
              and any(p.get("error") and "bad" in p.get("url", "") for p in pages)
              and any(not p.get("error") and "good" in p.get("url", "") for p in pages))
        record(ok, f"one bad page does not take the good one down: {label}",
               str([p.get("error", "ok")[:28] for p in pages]))

    # httpx really does put InvalidURL outside the family web.fetch catches --
    # the reason the blanket except above is not belt-and-braces.
    record(not issubclass(httpx.InvalidURL, httpx.HTTPError),
           "httpx.InvalidURL is not an httpx.HTTPError (the gap that caused the 500)")

    real = web.fetch
    web.fetch = asyncio.run(stub(web.WebError("x")))
    try:
        M._SPENT["pages"] = 0
        out = call("web_read", {"urls": ["https://good.example/"], "max_chars": "lots"})
        record(bool(out.get("pages")), "a max_chars that is not a number does not raise",
               str(out.get("pages", [{}])[0].get("url", ""))[:40])
        M._SPENT["pages"] = 0
        out = call("web_read", {"urls": ["https://good.example/"], "max_chars": [3000]})
        record(bool(out.get("pages")), "a max_chars that is a list does not raise either")
    finally:
        web.fetch = real

    # --- note / verify with the wrong types --------------------------------
    before = len(M._NOTES)
    out = call("note", {"notes": [
        {"claim": "a real one", "source": "https://x.example/"},
        {"claim": 42, "source": "https://y.example/"},
        {"claim": "restricted", "source": "https://z.example/", "restriction": ["2026", "EU"]},
        "not an object",
    ]})
    kept = out.get("noted") or 0
    record(isinstance(out, dict) and "error" not in out,
           "note with mixed types answers instead of failing", str(list(out))[:60])
    record(len(M._NOTES) - before == kept and kept == 3,
           "every note it says it kept is one it recorded, and the bad entries are dropped",
           f"noted={kept} recorded={len(M._NOTES) - before}")
    claims = [n["claim"] for _ts, _s, n in list(M._NOTES)[-kept:]] if kept else []
    record("42" in claims and any(c == "restricted" for c in claims),
           "a number became its text, a list-valued restriction did not stop the note", str(claims)[:70])

    out = call("verify", {"checks": [
        {"claim": "x", "source": "https://x.example/", "result": 1},
        {"claim": ["nope"], "source": "https://y.example/"},
    ]})
    record(isinstance(out, dict) and "error" not in out,
           "verify with wrong types answers instead of failing", str(list(out))[:60])

    # a single item, not a list, still works (the documented shortcut)
    out = call("note", {"claim": "single", "source": "https://s.example/"})
    record(isinstance(out, dict) and "error" not in out, "a single note is still accepted")

    # --- a spec file that parses but is not a spec -------------------------
    tmp = Path(tempfile.mkdtemp(prefix="mcp-specs-"))
    old_dir = M._SPECS_DIR
    try:
        (tmp / "good.json").write_text(json.dumps({"name": "good", "steps": [1, 2]}))
        (tmp / "oops.json").write_text("[]")
        (tmp / "half.json").write_text("{ not json")
        M._SPECS_DIR = str(tmp)
        out = call("flows_list", {})
        names = [f["name"] for f in out.get("flows", [])]
        record(names == ["good"], "a spec that is a list is skipped like an unreadable one", str(names))
    finally:
        M._SPECS_DIR = old_dir
        for f in tmp.iterdir():
            f.unlink()
        tmp.rmdir()

    # --- a JSON-RPC batch carrying something that is not a message ---------
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    app.include_router(M.router)
    with TestClient(app) as client:
        r = client.post("/mcp", json=[{"jsonrpc": "2.0", "id": 1, "method": "ping"}, 7])
        ok = r.status_code == 200
        body = r.json() if ok else []
        answered = [m.get("id") for m in body] if isinstance(body, list) else []
        record(ok and 1 in answered,
               "a scalar in a batch does not take the valid messages with it",
               f"HTTP {r.status_code}, answered ids {answered}")
        r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "ping"})
        record(r.status_code == 200 and r.json().get("id") == 2, "a plain ping still answers")

    M.end_turn()
    fails = [r for r in results if r[0] == "FAIL"]
    print(f"\n{len(results) - len(fails)} passed, {len(fails)} failed")
    for _, s, d in fails:
        print(f"  FAILED  {s}: {d}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
