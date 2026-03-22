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
