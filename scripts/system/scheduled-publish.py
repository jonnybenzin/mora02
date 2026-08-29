#!/usr/bin/env python3
"""mora02 scheduled-publish — poll Baserow for due 'ready' posts and publish them.

Replaces the ActivePieces pair SM_scheduled_publish (cron that flagged due posts) +
SM_publish_linkedIn (webhook that published). Baserow stays the planning cockpit —
posts are entered and scheduled there (or via the Pilot social interface, which
references the same table). This loop is only the automation glue: find rows that
are ready AND due AND not yet published, run each through the native
`publish.linkedin` step, and — ONLY on a real success — write the result back to
Baserow (status=published, post_id, post_url). Iteration lives here, not in the
pipeline: one post = one publish call.

Deliberately writes NO post_id on failure — the old AP flow wrote back a URN even
when the publish had really failed (expired token), leaving "ghost" post_ids that
looked published but were not. Here a failed row stays `ready` for the next tick.

Run by a systemd timer (mora02-scheduled-publish.timer). Environment:
  BASEROW_TOKEN     required (from /opt/mora02/docker/.env)
  BASEROW_URL       default http://mora02.local:8085
  STEP_RUNNER_URL   default http://127.0.0.1:8096
  SM_TABLE_ID       default 557
Flags: --dry-run (list what would publish; no publish, no write-back), --verbose.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASEROW_URL = os.environ.get("BASEROW_URL", "http://mora02.local:8085").rstrip("/")
# script-runner listens on 127.0.0.1 only since the stack ports were bound to
# localhost (4ac1a22), so the LAN name mora02.local no longer reaches it. This
# script runs on the host itself, so loopback is the correct address. Baserow
# below keeps the LAN name: 8085 stays open on purpose for phone and laptop.
STEP_RUNNER_URL = os.environ.get("STEP_RUNNER_URL", "http://127.0.0.1:8096").rstrip("/")
TABLE = os.environ.get("SM_TABLE_ID", "557")
TOKEN = os.environ.get("BASEROW_TOKEN")


def _baserow(method: str, path: str, body: dict | None = None) -> dict:
    url = f"{BASEROW_URL}/api/database/{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Authorization": f"Token {TOKEN}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def _status_value(row: dict) -> str | None:
    st = row.get("status")
    return st.get("value") if isinstance(st, dict) else st


def _is_due(row: dict, now: datetime) -> bool:
    """A row is due when it is 'ready', has no post_id yet, and its schedule has passed."""
    if _status_value(row) != "ready":
        return False
    if row.get("post_id"):  # idempotency: already carries a post id
        return False
    sched = row.get("scheduled_for")
    if not sched:
        return False
    try:
        due = datetime.fromisoformat(str(sched).replace("Z", "+00:00"))
    except ValueError:
        return False
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    return due <= now


def _media_ref(media_path: str | None) -> str | None:
    """Turn a Baserow media_path URL into an asset ref, or None for a text-only post.

    Inverse of the store→nginx mapping: most tool outputs are served under
    ``/tool-assets/<store>/…`` and ComfyUI directly under ``/comfyui/wip/…``.
    An unrecognised layout yields None (posts as text-only) rather than a guess.
    """
    if not media_path:
        return None
    if "/tool-assets/" in media_path:
        return "asset://" + media_path.split("/tool-assets/", 1)[1]
    if "/comfyui/wip/" in media_path:
        return "asset://comfyui/" + media_path.split("/comfyui/wip/", 1)[1]
    return None


def _publish(ref: str | None, caption: str) -> dict:
    url = f"{STEP_RUNNER_URL}/pipeline/step/publish.linkedin?" + urllib.parse.urlencode(
        {"text": caption or ""}
    )
    req = urllib.request.Request(url, data=(ref or "").encode(), method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())


def main() -> int:
    ap = argparse.ArgumentParser(description="Publish due Baserow social posts.")
    ap.add_argument("--dry-run", action="store_true",
                    help="list what would publish; no publish, no write-back")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    if not TOKEN:
        print("ERROR: BASEROW_TOKEN not set", file=sys.stderr)
        return 1

    now = datetime.now(timezone.utc)
    try:
        rows = _baserow("GET", f"rows/table/{TABLE}/?user_field_names=true&size=200")["results"]
    except urllib.error.URLError as e:
        # Baserow unreachable — typically it is not up yet shortly after a boot. From
        # here nothing is knowable, so leave the work to the next tick instead of dying
        # with a traceback: an unhandled exception pops an Apport crash dialog on the
        # desktop, and a refused connection is an expected condition, not a bug.
        print(f"ERROR: Baserow unreachable at {BASEROW_URL}: {e.reason}", file=sys.stderr)
        return 1
    due = [r for r in rows if _is_due(r, now)]
    print(f"[{now.isoformat(timespec='seconds')}] table {TABLE}: {len(rows)} rows, "
          f"{len(due)} due{' (dry-run)' if args.dry_run else ''}")

    published = failed = 0
    for row in due:
        rid = row["id"]
        name = row.get("Name") or rid
        ref = _media_ref(row.get("media_path"))
        caption = row.get("caption_master") or ""
        kind = "image" if ref else "text-only"

        if args.dry_run:
            print(f"  [dry-run] row {rid} ({name}) [{kind}]"
                  + (f" ref={ref}" if args.verbose else ""))
            continue

        try:
            res = _publish(ref, caption)
            post_url = res.get("out")
            post_id = (res.get("log") or {}).get("post_id") or post_url
            _baserow("PATCH", f"rows/table/{TABLE}/{rid}/?user_field_names=true", {
                "status": "published",
                "post_id": post_id,
                "post_url": post_url,
                "publish": False,
                "published_at": now.isoformat(),
            })
            print(f"  published row {rid} ({name}) [{kind}] -> {post_url}")
            published += 1
        except urllib.error.HTTPError as e:
            print(f"  FAILED row {rid} ({name}): HTTP {e.code} {e.read().decode()[:200]}",
                  file=sys.stderr)
            failed += 1  # left 'ready' — no post_id written, retried next tick
        except Exception as e:  # noqa: BLE001 — one bad row must not sink the batch
            print(f"  FAILED row {rid} ({name}): {type(e).__name__}: {e}", file=sys.stderr)
            failed += 1

    if not args.dry_run:
        print(f"  done: {published} published, {failed} failed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
