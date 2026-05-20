"""Baserow HTTP client — portable from apps/pilot/baserow_client.py.

Changes vs. the original Pilot module:
  - No `from config import settings`. Token + URL are read from env via
    `mora02_core.auth`.
  - Every async function takes a `user_id: str = "default"` parameter.
    Currently threaded through but not used for filtering — multi-user
    (E7) is a data-structure prep, not active auth.
  - `print()` replaced by the structured logger from mora02_core._common.
  - Table IDs are module-level constants for now (Phase 1.2b/c will
    replace them with a `schema.py`-generated table-name mapping).
"""

import json as _json
from datetime import datetime, timezone

import httpx

from mora02_core import auth
from mora02_core._common import get_logger


log = get_logger("mora02_core.baserow.client")


# ----------------------------------------------------------------------------
# Connection (lazy — token is fetched fresh per call so module import never
# fails for apps that don't actually consume Baserow).
# ----------------------------------------------------------------------------

def headers() -> dict[str, str]:
    """Build a Baserow request header dict (auth + JSON + virtual host).

    Public helper so callers that do direct httpx requests can use it. Internal
    callers use the same function under the alias ``_headers``.
    """
    return {
        "Authorization": f"Token {auth.require('BASEROW_TOKEN')}",
        "Content-Type": "application/json",
        "Host": "mora02.local:8085",
    }


def url() -> str:
    """Return the Baserow base URL (``BASEROW_URL`` env or container default)."""
    return auth.get("BASEROW_URL", "http://baserow:80")


# Internal aliases — kept so older code in this module stays terse.
_headers = headers
_url = url


# ----------------------------------------------------------------------------
# Table IDs — placeholder until Phase 1.2c replaces them with schema.py.
# Keep in sync with apps/pilot/config.py.
# ----------------------------------------------------------------------------

TABLE_SESSIONS = 571
TABLE_CONTEXT = 572
TABLE_KNOWN_ISSUES = 573
TABLE_PERSONAS = 575
TABLE_FEEDBACK = 576
TABLE_BUCKETS = 577
TABLE_STYLE_PACKS = 578
TABLE_POSTS = 557


# ============================================================
# SESSION HELPERS
# ============================================================

async def write_session(data: dict, *, user_id: str = "default") -> dict | None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{_url()}/api/database/rows/table/{TABLE_SESSIONS}/?user_field_names=true",
            headers=_headers(), json=data,
        )
        if resp.status_code in (200, 201):
            return resp.json()
        log.warning("write_session failed: %d %s", resp.status_code, resp.text[:200])
        return None


async def read_last_sessions(n: int = 3, *, user_id: str = "default") -> list[dict]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{_url()}/api/database/rows/table/{TABLE_SESSIONS}/?user_field_names=true&size={n}",
            headers=_headers(),
        )
        if resp.status_code == 200:
            results = resp.json().get("results", [])
            return sorted(results, key=lambda r: r.get("id", 0), reverse=True)[:n]
        return []


async def read_all_sessions(*, user_id: str = "default") -> list[dict]:
    """Read all sessions for cost aggregation."""
    all_results: list[dict] = []
    page = 1
    async with httpx.AsyncClient(timeout=10.0) as client:
        while True:
            resp = await client.get(
                f"{_url()}/api/database/rows/table/{TABLE_SESSIONS}/?user_field_names=true&size=200&page={page}",
                headers=_headers(),
            )
            if resp.status_code != 200:
                break
            data = resp.json()
            all_results.extend(data.get("results", []))
            if not data.get("next"):
                break
            page += 1
    return all_results


# ============================================================
# CONTEXT HELPERS
# ============================================================

async def read_context(
    key: str | None = None, *, user_id: str = "default"
) -> list[dict] | str | None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{_url()}/api/database/rows/table/{TABLE_CONTEXT}/?user_field_names=true&size=50",
            headers=_headers(),
        )
        if resp.status_code == 200:
            rows = resp.json().get("results", [])
            if key:
                for r in rows:
                    if r.get("key") == key:
                        return r.get("value")
                return None
            return rows
        return []


async def write_context(
    key: str, value: str, *, user_id: str = "default"
) -> dict | None:
    existing = await read_context(user_id=user_id)
    row_id = None
    if isinstance(existing, list):
        for r in existing:
            if r.get("key") == key:
                row_id = r.get("id")
                break

    async with httpx.AsyncClient(timeout=10.0) as client:
        if row_id:
            resp = await client.patch(
                f"{_url()}/api/database/rows/table/{TABLE_CONTEXT}/{row_id}/?user_field_names=true",
                headers=_headers(),
                json={"value": value, "updated_at": datetime.now(timezone.utc).isoformat()},
            )
        else:
            resp = await client.post(
                f"{_url()}/api/database/rows/table/{TABLE_CONTEXT}/?user_field_names=true",
                headers=_headers(),
                json={"key": key, "value": value, "updated_at": datetime.now(timezone.utc).isoformat()},
            )
        if resp.status_code in (200, 201):
            return resp.json()
        log.warning("write_context failed: %d %s", resp.status_code, resp.text[:200])
        return None


# ============================================================
# KNOWN ISSUES
# ============================================================

async def read_known_issues(*, user_id: str = "default") -> list[dict]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{_url()}/api/database/rows/table/{TABLE_KNOWN_ISSUES}/?user_field_names=true&size=50",
            headers=_headers(),
        )
        if resp.status_code == 200:
            return resp.json().get("results", [])
        return []


# ============================================================
# PERSONAS
# ============================================================

async def read_personas(*, user_id: str = "default") -> list[dict]:
    """Read all active personas from bot_personas table, sorted by sort_order."""
    try:
        url = f"{_url()}/api/database/rows/table/{TABLE_PERSONAS}/"
        params = {
            "user_field_names": "true",
            "filter__active__boolean": "true",
            "order_by": "sort_order",
            "size": 50,
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers=_headers(), params=params)
            if resp.status_code == 200:
                return resp.json().get("results", [])
            log.warning("read_personas failed: %d %s", resp.status_code, resp.text[:200])
    except Exception as e:
        log.exception("read_personas error: %r", e)
    return []


async def create_persona_row(
    name: str,
    icon: str,
    description: str,
    prompt: str,
    briefing_target: str,
    *,
    user_id: str = "default",
) -> dict | None:
    """Create a new persona row in Baserow."""
    try:
        url = f"{_url()}/api/database/rows/table/{TABLE_PERSONAS}/"
        params = {"user_field_names": "true"}
        payload = {
            "name": name, "icon": icon, "description": description,
            "prompt": prompt, "briefing_target": briefing_target,
            "sort_order": 99, "active": True, "usage_count": 0,
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, headers=_headers(), params=params, json=payload)
            if resp.status_code in (200, 201):
                return resp.json()
            log.warning("create_persona failed: %d %s", resp.status_code, resp.text[:200])
    except Exception as e:
        log.exception("create_persona error: %r", e)
    return None


async def increment_persona_usage(
    persona_row_id: int, current_count: int, *, user_id: str = "default"
) -> None:
    """Increment usage_count for a persona."""
    try:
        url = f"{_url()}/api/database/rows/table/{TABLE_PERSONAS}/{persona_row_id}/"
        params = {"user_field_names": "true"}
        payload = {"usage_count": current_count + 1}
        async with httpx.AsyncClient(timeout=10) as client:
            await client.patch(url, headers=_headers(), params=params, json=payload)
    except Exception as e:
        log.exception("increment_persona_usage error: %r", e)


async def update_persona(
    row_id: int, data: dict, *, user_id: str = "default"
) -> dict | None:
    """Update a persona row (e.g. archive via {'active': False})."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.patch(
            f"{_url()}/api/database/rows/table/{TABLE_PERSONAS}/{row_id}/?user_field_names=true",
            headers=_headers(), json=data,
        )
        if resp.status_code == 200:
            return resp.json()
        return None


# ============================================================
# FEEDBACK
# ============================================================

async def write_feedback(data: dict, *, user_id: str = "default") -> dict | None:
    """Create a new feedback row in Baserow."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{_url()}/api/database/rows/table/{TABLE_FEEDBACK}/?user_field_names=true",
            headers=_headers(), json=data,
        )
        if resp.status_code in (200, 201):
            return resp.json()
        log.warning("write_feedback failed: %d %s", resp.status_code, resp.text[:200])
        return None


async def list_feedback(
    status_filter: str | None = None, *, user_id: str = "default"
) -> list[dict]:
    """Read feedback entries, optionally filtered by status. Newest first."""
    all_results: list[dict] = []
    page = 1
    async with httpx.AsyncClient(timeout=10.0) as client:
        while True:
            url = (
                f"{_url()}/api/database/rows/table/{TABLE_FEEDBACK}/"
                f"?user_field_names=true&size=50&page={page}"
            )
            if status_filter:
                url += f"&filter__Status__equal={status_filter}"
            resp = await client.get(url, headers=_headers())
            if resp.status_code != 200:
                break
            data = resp.json()
            all_results.extend(data.get("results", []))
            if not data.get("next"):
                break
            page += 1
    return sorted(all_results, key=lambda r: r.get("id", 0), reverse=True)


async def update_feedback(
    row_id: int, data: dict, *, user_id: str = "default"
) -> dict | None:
    """Update a feedback row (e.g. change status)."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.patch(
            f"{_url()}/api/database/rows/table/{TABLE_FEEDBACK}/{row_id}/?user_field_names=true",
            headers=_headers(), json=data,
        )
        if resp.status_code == 200:
            return resp.json()
        return None


# ============================================================
# BUCKETS
# ============================================================

async def save_bucket(
    name: str, items: list, *, user_id: str = "default"
) -> dict | None:
    """Save a named bucket to Baserow."""
    row_data = {
        "Name": name,
        "Items": _json.dumps(items, ensure_ascii=False),
        "item_count": len(items),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{_url()}/api/database/rows/table/{TABLE_BUCKETS}/?user_field_names=true",
            headers=_headers(), json=row_data,
        )
        if resp.status_code in (200, 201):
            return resp.json()
        log.warning("save_bucket failed: %d %s", resp.status_code, resp.text[:200])
        return None


async def list_buckets(*, user_id: str = "default") -> list[dict]:
    """List all saved buckets, newest first."""
    all_results: list[dict] = []
    page = 1
    async with httpx.AsyncClient(timeout=10.0) as client:
        while True:
            resp = await client.get(
                f"{_url()}/api/database/rows/table/{TABLE_BUCKETS}/?user_field_names=true&size=50&page={page}",
                headers=_headers(),
            )
            if resp.status_code != 200:
                break
            data = resp.json()
            all_results.extend(data.get("results", []))
            if not data.get("next"):
                break
            page += 1
    return sorted(all_results, key=lambda r: r.get("id", 0), reverse=True)


async def delete_bucket(row_id: int, *, user_id: str = "default") -> bool:
    """Delete a saved bucket."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.delete(
            f"{_url()}/api/database/rows/table/{TABLE_BUCKETS}/{row_id}/",
            headers=_headers(),
        )
        return resp.status_code == 204


# ============================================================
# STYLE PACKS
# ============================================================

async def save_style_pack(data: dict, *, user_id: str = "default") -> dict | None:
    """Create a new style pack row in Baserow."""
    row_data = {
        "name": data.get("name", ""),
        "source_type": data.get("source_type", "folder"),
        "source_path": data.get("source_path", ""),
        "image_count": data.get("image_count", 0),
        "preview_url": data.get("preview_url", ""),
        "status": data.get("status", "active"),
        "style_weight": data.get("style_weight", 0.7),
        "lora_path": "",
        "lora_trigger": "",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{_url()}/api/database/rows/table/{TABLE_STYLE_PACKS}/?user_field_names=true",
            headers=_headers(), json=row_data,
        )
        if resp.status_code in (200, 201):
            return resp.json()
        log.warning("save_style_pack failed: %d %s", resp.status_code, resp.text[:200])
        return None


async def list_style_packs(*, user_id: str = "default") -> list[dict]:
    """List all style packs, newest first."""
    all_results: list[dict] = []
    page = 1
    async with httpx.AsyncClient(timeout=10.0) as client:
        while True:
            resp = await client.get(
                f"{_url()}/api/database/rows/table/{TABLE_STYLE_PACKS}/?user_field_names=true&size=50&page={page}",
                headers=_headers(),
            )
            if resp.status_code != 200:
                break
            data = resp.json()
            all_results.extend(data.get("results", []))
            if not data.get("next"):
                break
            page += 1
    return sorted(all_results, key=lambda r: r.get("id", 0), reverse=True)


async def get_style_pack(row_id: int, *, user_id: str = "default") -> dict | None:
    """Get a single style pack by row ID."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{_url()}/api/database/rows/table/{TABLE_STYLE_PACKS}/{row_id}/?user_field_names=true",
            headers=_headers(),
        )
        if resp.status_code == 200:
            return resp.json()
        return None


async def get_style_pack_by_name(name: str, *, user_id: str = "default") -> dict | None:
    """Get a style pack by name (for --style lookup)."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{_url()}/api/database/rows/table/{TABLE_STYLE_PACKS}/?user_field_names=true&filter__name__equal={name}&size=1",
            headers=_headers(),
        )
        if resp.status_code == 200:
            results = resp.json().get("results", [])
            return results[0] if results else None
        return None


async def update_style_pack(
    row_id: int, data: dict, *, user_id: str = "default"
) -> dict | None:
    """Update a style pack row."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.patch(
            f"{_url()}/api/database/rows/table/{TABLE_STYLE_PACKS}/{row_id}/?user_field_names=true",
            headers=_headers(), json=data,
        )
        if resp.status_code == 200:
            return resp.json()
        return None


async def delete_style_pack(row_id: int, *, user_id: str = "default") -> bool:
    """Delete a style pack."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.delete(
            f"{_url()}/api/database/rows/table/{TABLE_STYLE_PACKS}/{row_id}/",
            headers=_headers(),
        )
        return resp.status_code == 204


# ============================================================
# POSTS (sm_content)
# ============================================================

async def list_posts(*, user_id: str = "default") -> list[dict]:
    """Read all social media posts, newest first."""
    all_results: list[dict] = []
    page = 1
    async with httpx.AsyncClient(timeout=10.0) as client:
        while True:
            url = (
                f"{_url()}/api/database/rows/table/{TABLE_POSTS}/"
                f"?user_field_names=true&size=50&page={page}&order_by=-created_at"
            )
            resp = await client.get(url, headers=_headers())
            if resp.status_code != 200:
                break
            data = resp.json()
            all_results.extend(data.get("results", []))
            if not data.get("next"):
                break
            page += 1
    return all_results


async def create_post(data: dict, *, user_id: str = "default") -> dict | None:
    """Create a new sm_content row."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{_url()}/api/database/rows/table/{TABLE_POSTS}/?user_field_names=true",
            headers=_headers(), json=data,
        )
        if resp.status_code in (200, 201):
            return resp.json()
        return None


async def update_post(
    row_id: int, data: dict, *, user_id: str = "default"
) -> dict | None:
    """Update an sm_content row."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.patch(
            f"{_url()}/api/database/rows/table/{TABLE_POSTS}/{row_id}/?user_field_names=true",
            headers=_headers(), json=data,
        )
        if resp.status_code == 200:
            return resp.json()
        return None


# ============================================================
# FORMATTERS (pure sync, no HTTP)
# ============================================================

def format_sessions_context(sessions: list[dict]) -> str:
    if not sessions:
        return "No previous sessions found."
    parts = ["## Recent Sessions"]
    for s in sessions:
        goal = s.get("goal") or "n/a"
        summary = s.get("summary") or "n/a"
        open_items = s.get("open_items") or "none"
        model = s.get("model_used") or "?"
        parts.append(f"- **{goal}** ({model})\n  {summary}\n  Open: {open_items}")
    return "\n".join(parts)


def format_known_issues(issues: list[dict]) -> str:
    if not issues:
        return "No known issues."
    parts = ["## Known Issues & Solutions"]
    for i in issues:
        name = i.get("Name") or "?"
        problem = i.get("problem") or ""
        solution = i.get("solution") or ""
        tags = i.get("tags") or ""
        parts.append(f"### {name} [{tags}]\n**Problem:** {problem}\n**Solution:** {solution}")
    return "\n\n".join(parts)


def format_context_table(rows: list[dict]) -> str:
    if not rows:
        return "No context data."
    parts = ["## System Context"]
    for r in rows:
        key = r.get("key") or ""
        value = r.get("value") or ""
        if key:
            parts.append(f"- **{key}:** {value}")
    return "\n".join(parts)
