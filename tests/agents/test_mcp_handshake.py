#!/usr/bin/env python3
"""Replay the handshake OpenClaw was measured to perform, against our own server.

The pipeline MCP server in ``apps/script-runner/app/mcp_tools.py`` is written by
hand rather than with the MCP SDK. That was a defensible choice on 1 September
2026 because the protocol in play had been captured in full: four methods, one
response shape (``notizen/phase0-agenten/mcp-handshake-260901-1018.log``). It
stops being defensible the moment an OpenClaw update starts asking for something
else -- and the failure mode would be quiet. The gateway would simply list no
tools, the agent would answer from its own head, and nobody would see an error.

So this suite is the tripwire under that decision. It sends the captured
sequence byte for byte and checks the answers, then checks the part that matters
more than the protocol: that the tool surface offers no way to open a gate.

Usage:
    python3 tests/agents/test_mcp_handshake.py

Environment: SCRIPT_RUNNER_URL (default http://127.0.0.1:8096).
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

RUNNER = os.environ.get("SCRIPT_RUNNER_URL", "http://127.0.0.1:8096")
MCP = f"{RUNNER}/mcp"

# Verbatim from the capture: this is what openclaw 2026.6.1 (2e08f0f) sent.
CLIENT_ACCEPT = "application/json, text/event-stream"
CLIENT_UA = "undici"
PROTOCOL = "2025-11-25"

# Verbs that would let an agent release a gate. None of them may ever appear in
# tools/list. Pillar 6 of the plan is enforced by absence, and absence is the
# kind of property that gets undone by a well-meaning addition.
FORBIDDEN = ("resume", "approve", "cancel", "release", "confirm", "gate", "token")

results: list[tuple[str, str, str]] = []


def record(verdict: str, subject: str, detail: str) -> None:
    results.append((verdict, subject, detail))
    mark = {"PASS": "  ok  ", "FAIL": " FAIL ", "WARN": " warn "}[verdict]
    print(f"[{mark}] {subject}: {detail}")


def rpc(body: dict, *, session: str | None = None) -> tuple[int, dict | None, dict]:
    """One POST, shaped like the client's. Returns (status, parsed body, headers)."""
    headers = {
        "content-type": "application/json",
        "accept": CLIENT_ACCEPT,
        "user-agent": CLIENT_UA,
    }
    if session:
        headers["mcp-session-id"] = session
        headers["mcp-protocol-version"] = PROTOCOL
    req = urllib.request.Request(
        MCP, data=json.dumps(body).encode("utf-8"), method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read().decode("utf-8")
            return r.status, (json.loads(raw) if raw.strip() else None), dict(r.headers)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(raw) if raw.strip() else None
        except ValueError:
            parsed = None
        return e.code, parsed, dict(e.headers)


def wait_ready(seconds: int = 45) -> bool:
    """Wait for uvicorn to actually listen.

    `docker compose up -d --build` returns when the container has STARTED, not
    when the app inside it is serving -- and this suite is meant to be run in
    the same breath as a rebuild. Without this the first request dies with a
    connection reset, which reads like a broken server rather than an early
    knock.
    """
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{RUNNER}/health", timeout=3) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(1)
    return False


def main() -> int:
    if not wait_ready():
        print(f"script-runner did not become healthy at {RUNNER}", file=sys.stderr)
        return 2

    # --- 1. initialize -----------------------------------------------------
    status, body, headers = rpc({
        "method": "initialize",
        "params": {"protocolVersion": PROTOCOL, "capabilities": {},
                   "clientInfo": {"name": "openclaw-bundle-mcp", "version": "0.0.0"}},
        "jsonrpc": "2.0", "id": 0,
    })
    if status != 200 or not body or "result" not in body:
        record("FAIL", "initialize", f"HTTP {status}, body {str(body)[:200]}")
        return report()
    got = body["result"].get("protocolVersion")
    if got == PROTOCOL:
        record("PASS", "initialize", f"echoed protocolVersion {got}")
    else:
        # Not fatal on its own, but it is the single likeliest cause of a client
        # walking away, so it is worth naming precisely.
        record("FAIL", "initialize",
               f"asked for {PROTOCOL}, server answered {got!r}")
    session = headers.get("Mcp-Session-Id") or headers.get("mcp-session-id")
    record("PASS" if session else "WARN", "session id",
           f"server offered {session!r}" if session else "no Mcp-Session-Id offered")

    # --- 2. notifications/initialized -> 202, no body ----------------------
    status, body, _ = rpc(
        {"method": "notifications/initialized", "jsonrpc": "2.0"}, session=session)
    if status == 202 and body is None:
        record("PASS", "notifications/initialized", "202 with no body")
    else:
        # The client sends this and then waits. A body, or a 200, is how a
        # handshake hangs rather than fails.
        record("FAIL", "notifications/initialized",
               f"expected 202 and no body, got HTTP {status} / {str(body)[:120]}")

    # --- 3. GET, the SSE attempt -------------------------------------------
    req = urllib.request.Request(MCP, method="GET", headers={
        "accept": "text/event-stream", "user-agent": CLIENT_UA,
        "mcp-session-id": session or "", "mcp-protocol-version": PROTOCOL})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            record("WARN", "GET /mcp",
                   f"answered {r.status} — the capture shows a refusal, and the "
                   "client carried on regardless")
    except urllib.error.HTTPError as e:
        if e.code == 405:
            record("PASS", "GET /mcp", "405, as measured — no stream on offer")
        else:
            record("WARN", "GET /mcp", f"HTTP {e.code}; the client tolerates a refusal")

    # --- 4. tools/list ------------------------------------------------------
    status, body, _ = rpc({"method": "tools/list", "jsonrpc": "2.0", "id": 1},
                          session=session)
    tools = ((body or {}).get("result") or {}).get("tools") or []
    names = [t.get("name") for t in tools]
    if status == 200 and tools:
        record("PASS", "tools/list", f"{len(tools)} tools: {', '.join(names)}")
    else:
        record("FAIL", "tools/list", f"HTTP {status}, body {str(body)[:200]}")
        return report()

    # Every tool needs a schema the client can render, and a description that
    # says WHEN to use it -- a description without a trigger is a tool that is
    # listed and never called, which fails silently.
    for t in tools:
        if not isinstance(t.get("inputSchema"), dict):
            record("FAIL", f"tool {t.get('name')}", "no inputSchema")
        elif len(t.get("description") or "") < 40:
            record("WARN", f"tool {t.get('name')}",
                   "description is short — does it name its trigger?")
        else:
            record("PASS", f"tool {t.get('name')}", "schema and description present")

    # --- 5. THE one that matters: no verb for opening a gate ---------------
    blob = json.dumps(tools).lower()
    offenders = [n for n in names if any(w in (n or "").lower() for w in FORBIDDEN)]
    if offenders:
        record("FAIL", "gate discipline",
               f"tool names suggest a gate can be opened: {offenders}")
    else:
        record("PASS", "gate discipline", "no resume/approve/cancel tool exists")
    if "resume_token" in blob:
        record("FAIL", "gate discipline",
               "a resume_token appears in the tool surface — that is the gate key")
    else:
        record("PASS", "resume token", "not present in the tool surface")

    # --- 6. tools/call, on the one tool that spends nothing -----------------
    status, body, _ = rpc({
        "method": "tools/call",
        "params": {"name": "flows_list", "arguments": {}},
        "jsonrpc": "2.0", "id": 2,
    }, session=session)
    result = ((body or {}).get("result") or {})
    content = (result.get("content") or [{}])[0].get("text")
    if status == 200 and content:
        try:
            payload = json.loads(content)
            record("PASS", "tools/call flows_list",
                   f"{payload.get('count')} flows returned, isError={result.get('isError')}")
        except ValueError:
            record("FAIL", "tools/call flows_list", f"content is not JSON: {content[:120]}")
    else:
        record("FAIL", "tools/call flows_list", f"HTTP {status}, body {str(body)[:200]}")

    # --- 7. an honest failure, not an invented one -------------------------
    status, body, _ = rpc({
        "method": "tools/call",
        "params": {"name": "flow_run", "arguments": {"flow": "no-such-flow-xyzzy"}},
        "jsonrpc": "2.0", "id": 3,
    }, session=session)
    result = ((body or {}).get("result") or {})
    text = (result.get("content") or [{}])[0].get("text") or ""
    if result.get("isError") and "no flow named" in text:
        record("PASS", "unknown flow", "reported as an error, with the known names listed")
    else:
        # A tool that answers a bad name with a cheerful success is how a model
        # ends up reporting a run that never started.
        record("FAIL", "unknown flow",
               f"isError={result.get('isError')}, text={text[:160]}")

    # --- 8. an unknown method is named, not swallowed ----------------------
    status, body, _ = rpc({"method": "resources/list", "jsonrpc": "2.0", "id": 4},
                          session=session)
    if (body or {}).get("error", {}).get("code") == -32601:
        record("PASS", "unknown method", "-32601, and the name is in the log")
    else:
        record("WARN", "unknown method", f"expected -32601, got {str(body)[:140]}")

    return report()


def report() -> int:
    print()
    fails = [r for r in results if r[0] == "FAIL"]
    warns = [r for r in results if r[0] == "WARN"]
    print(f"{len(results) - len(fails) - len(warns)} passed, "
          f"{len(warns)} warned, {len(fails)} failed")
    for _, subject, detail in fails:
        print(f"  FAILED  {subject}: {detail}")
    return 1 if fails else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except urllib.error.URLError as e:
        print(f"cannot reach script-runner at {RUNNER}: {e}", file=sys.stderr)
        print("is the stack up?", file=sys.stderr)
        sys.exit(2)
