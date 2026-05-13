import httpx
from datetime import datetime, timezone
from config import settings

BASEROW_HEADERS = {
    "Authorization": f"Token {settings.baserow_token}",
    "Content-Type": "application/json",
    "Host": "mora02.local:8085",
}


async def write_session(data: dict) -> dict | None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{settings.baserow_url}/api/database/rows/table/{settings.baserow_table_sessions}/?user_field_names=true",
            headers=BASEROW_HEADERS, json=data)
        if resp.status_code in [200, 201]:
            return resp.json()
        return None


async def read_last_sessions(n: int = 3) -> list[dict]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{settings.baserow_url}/api/database/rows/table/{settings.baserow_table_sessions}/?user_field_names=true&size={n}",
            headers=BASEROW_HEADERS)
        if resp.status_code == 200:
            results = resp.json().get("results", [])
            # Return newest first (highest ID = newest)
            return sorted(results, key=lambda r: r.get("id", 0), reverse=True)[:n]
        return []


async def read_all_sessions() -> list[dict]:
    """Read all sessions for cost aggregation."""
    all_results = []
    page = 1
    async with httpx.AsyncClient(timeout=10.0) as client:
        while True:
            resp = await client.get(
                f"{settings.baserow_url}/api/database/rows/table/{settings.baserow_table_sessions}/?user_field_names=true&size=200&page={page}",
                headers=BASEROW_HEADERS)
            if resp.status_code != 200:
                break
            data = resp.json()
            all_results.extend(data.get("results", []))
            if not data.get("next"):
                break
            page += 1
    return all_results


async def read_context(key: str = None) -> list[dict] | str | None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{settings.baserow_url}/api/database/rows/table/{settings.baserow_table_context}/?user_field_names=true&size=50",
            headers=BASEROW_HEADERS)
        if resp.status_code == 200:
            rows = resp.json().get("results", [])
            if key:
                for r in rows:
                    if r.get("key") == key:
                        return r.get("value")
                return None
            return rows
        return []


async def read_known_issues() -> list[dict]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{settings.baserow_url}/api/database/rows/table/{settings.baserow_table_known_issues}/?user_field_names=true&size=50",
            headers=BASEROW_HEADERS)
        if resp.status_code == 200:
            return resp.json().get("results", [])
        return []


async def write_context(key: str, value: str) -> dict | None:
    existing = await read_context()
    row_id = None
    if isinstance(existing, list):
        for r in existing:
            if r.get("key") == key:
                row_id = r.get("id")
                break

    async with httpx.AsyncClient(timeout=10.0) as client:
        if row_id:
            resp = await client.patch(
                f"{settings.baserow_url}/api/database/rows/table/{settings.baserow_table_context}/{row_id}/?user_field_names=true",
                headers=BASEROW_HEADERS,
                json={"value": value, "updated_at": datetime.now(timezone.utc).isoformat()})
        else:
            resp = await client.post(
                f"{settings.baserow_url}/api/database/rows/table/{settings.baserow_table_context}/?user_field_names=true",
                headers=BASEROW_HEADERS,
                json={"key": key, "value": value, "updated_at": datetime.now(timezone.utc).isoformat()})
        if resp.status_code in [200, 201]:
            return resp.json()
        return None


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


# ============================================================
# PERSONA HELPERS
# ============================================================

async def read_personas() -> list[dict]:
    """Read all active personas from bot_personas table, sorted by sort_order."""
    try:
        url = f"{settings.baserow_url}/api/database/rows/table/{settings.baserow_table_personas}/"
        params = {
            "user_field_names": "true",
            "filter__active__boolean": "true",
            "order_by": "sort_order",
            "size": 50,
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers=BASEROW_HEADERS, params=params)
            if resp.status_code == 200:
                return resp.json().get("results", [])
    except Exception as e:
        print(f"[baserow] read_personas error: {e}")
    return []


async def create_persona_row(name: str, icon: str, description: str,
                              prompt: str, briefing_target: str) -> dict | None:
    """Create a new persona row in Baserow."""
    try:
        url = f"{settings.baserow_url}/api/database/rows/table/{settings.baserow_table_personas}/"
        params = {"user_field_names": "true"}
        payload = {
            "name": name, "icon": icon, "description": description,
            "prompt": prompt, "briefing_target": briefing_target,
            "sort_order": 99, "active": True, "usage_count": 0,
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, headers=BASEROW_HEADERS,
                                     params=params, json=payload)
            if resp.status_code in (200, 201):
                return resp.json()
            print(f"[baserow] create_persona error: {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        print(f"[baserow] create_persona error: {e}")
    return None


async def increment_persona_usage(persona_row_id: int, current_count: int) -> None:
    """Increment usage_count for a persona."""
    try:
        url = f"{settings.baserow_url}/api/database/rows/table/{settings.baserow_table_personas}/{persona_row_id}/"
        params = {"user_field_names": "true"}
        payload = {"usage_count": current_count + 1}
        async with httpx.AsyncClient(timeout=10) as client:
            await client.patch(url, headers=BASEROW_HEADERS,
                               params=params, json=payload)
    except Exception as e:
        print(f"[baserow] increment_persona_usage error: {e}")


# ============================================================
# FEEDBACK HELPERS
# ============================================================

async def write_feedback(data: dict) -> dict | None:
    """Create a new feedback row in Baserow."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{settings.baserow_url}/api/database/rows/table/{settings.baserow_table_feedback}/?user_field_names=true",
            headers=BASEROW_HEADERS, json=data)
        if resp.status_code in [200, 201]:
            return resp.json()
        print(f"[baserow] write_feedback error: {resp.status_code} {resp.text[:200]}")
        return None


async def list_feedback(status_filter: str = None) -> list[dict]:
    """Read feedback entries, optionally filtered by status. Newest first."""
    all_results = []
    page = 1
    async with httpx.AsyncClient(timeout=10.0) as client:
        while True:
            url = f"{settings.baserow_url}/api/database/rows/table/{settings.baserow_table_feedback}/?user_field_names=true&size=50&page={page}"
            if status_filter:
                url += f"&filter__Status__equal={status_filter}"
            resp = await client.get(url, headers=BASEROW_HEADERS)
            if resp.status_code != 200:
                break
            data = resp.json()
            all_results.extend(data.get("results", []))
            if not data.get("next"):
                break
            page += 1
    return sorted(all_results, key=lambda r: r.get("id", 0), reverse=True)


async def update_feedback(row_id: int, data: dict) -> dict | None:
    """Update a feedback row (e.g. change status)."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.patch(
            f"{settings.baserow_url}/api/database/rows/table/{settings.baserow_table_feedback}/{row_id}/?user_field_names=true",
            headers=BASEROW_HEADERS, json=data)
        if resp.status_code == 200:
            return resp.json()
        return None


# ============================================================
# BUCKET HELPERS
# ============================================================

async def save_bucket(name: str, items: list) -> dict | None:
    """Save a named bucket to Baserow."""
    import json as _json
    row_data = {
        "Name": name,
        "Items": _json.dumps(items, ensure_ascii=False),
        "item_count": len(items),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{settings.baserow_url}/api/database/rows/table/{settings.baserow_table_buckets}/?user_field_names=true",
            headers=BASEROW_HEADERS, json=row_data)
        if resp.status_code in [200, 201]:
            return resp.json()
        print(f"[baserow] save_bucket error: {resp.status_code} {resp.text[:200]}")
        return None


async def list_buckets() -> list[dict]:
    """List all saved buckets, newest first."""
    all_results = []
    page = 1
    async with httpx.AsyncClient(timeout=10.0) as client:
        while True:
            resp = await client.get(
                f"{settings.baserow_url}/api/database/rows/table/{settings.baserow_table_buckets}/?user_field_names=true&size=50&page={page}",
                headers=BASEROW_HEADERS)
            if resp.status_code != 200:
                break
            data = resp.json()
            all_results.extend(data.get("results", []))
            if not data.get("next"):
                break
            page += 1
    return sorted(all_results, key=lambda r: r.get("id", 0), reverse=True)


async def delete_bucket(row_id: int) -> bool:
    """Delete a saved bucket."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.delete(
            f"{settings.baserow_url}/api/database/rows/table/{settings.baserow_table_buckets}/{row_id}/",
            headers=BASEROW_HEADERS)
        return resp.status_code == 204


# ============================================================
# STYLE PACK HELPERS
# ============================================================

async def save_style_pack(data: dict) -> dict | None:
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
            f"{settings.baserow_url}/api/database/rows/table/{settings.baserow_table_style_packs}/?user_field_names=true",
            headers=BASEROW_HEADERS, json=row_data)
        if resp.status_code in [200, 201]:
            return resp.json()
        print(f"[baserow] save_style_pack error: {resp.status_code} {resp.text[:200]}")
        return None


async def list_style_packs() -> list[dict]:
    """List all style packs, newest first."""
    all_results = []
    page = 1
    async with httpx.AsyncClient(timeout=10.0) as client:
        while True:
            resp = await client.get(
                f"{settings.baserow_url}/api/database/rows/table/{settings.baserow_table_style_packs}/?user_field_names=true&size=50&page={page}",
                headers=BASEROW_HEADERS)
            if resp.status_code != 200:
                break
            data = resp.json()
            all_results.extend(data.get("results", []))
            if not data.get("next"):
                break
            page += 1
    return sorted(all_results, key=lambda r: r.get("id", 0), reverse=True)


async def get_style_pack(row_id: int) -> dict | None:
    """Get a single style pack by row ID."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{settings.baserow_url}/api/database/rows/table/{settings.baserow_table_style_packs}/{row_id}/?user_field_names=true",
            headers=BASEROW_HEADERS)
        if resp.status_code == 200:
            return resp.json()
        return None


async def get_style_pack_by_name(name: str) -> dict | None:
    """Get a style pack by name (for --style lookup)."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{settings.baserow_url}/api/database/rows/table/{settings.baserow_table_style_packs}/?user_field_names=true&filter__name__equal={name}&size=1",
            headers=BASEROW_HEADERS)
        if resp.status_code == 200:
            results = resp.json().get("results", [])
            return results[0] if results else None
        return None


async def update_style_pack(row_id: int, data: dict) -> dict | None:
    """Update a style pack row."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.patch(
            f"{settings.baserow_url}/api/database/rows/table/{settings.baserow_table_style_packs}/{row_id}/?user_field_names=true",
            headers=BASEROW_HEADERS, json=data)
        if resp.status_code == 200:
            return resp.json()
        return None


async def delete_style_pack(row_id: int) -> bool:
    """Delete a style pack."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.delete(
            f"{settings.baserow_url}/api/database/rows/table/{settings.baserow_table_style_packs}/{row_id}/",
            headers=BASEROW_HEADERS)
        return resp.status_code == 204


# ============================================================
# PERSONA UPDATE / ARCHIVE
# ============================================================

async def update_persona(row_id: int, data: dict) -> dict | None:
    """Update a persona row (e.g. archive via {'active': False})."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.patch(
            f"{settings.baserow_url}/api/database/rows/table/{settings.baserow_table_personas}/{row_id}/?user_field_names=true",
            headers=BASEROW_HEADERS, json=data)
        if resp.status_code == 200:
            return resp.json()
        return None


# ============================================================
# POST HELPERS (sm_content)
# ============================================================

async def list_posts() -> list[dict]:
    """Read all social media posts, newest first."""
    all_results = []
    page = 1
    async with httpx.AsyncClient(timeout=10.0) as client:
        while True:
            url = f"{settings.baserow_url}/api/database/rows/table/{settings.baserow_table_posts}/?user_field_names=true&size=50&page={page}&order_by=-created_at"
            resp = await client.get(url, headers=BASEROW_HEADERS)
            if resp.status_code != 200:
                break
            data = resp.json()
            all_results.extend(data.get("results", []))
            if not data.get("next"):
                break
            page += 1
    return all_results


async def create_post(data: dict) -> dict | None:
    """Create a new sm_content row."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{settings.baserow_url}/api/database/rows/table/{settings.baserow_table_posts}/?user_field_names=true",
            headers=BASEROW_HEADERS, json=data)
        if resp.status_code in [200, 201]:
            return resp.json()
        return None


async def update_post(row_id: int, data: dict) -> dict | None:
    """Update an sm_content row."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.patch(
            f"{settings.baserow_url}/api/database/rows/table/{settings.baserow_table_posts}/{row_id}/?user_field_names=true",
            headers=BASEROW_HEADERS, json=data)
        if resp.status_code == 200:
            return resp.json()
        return None
