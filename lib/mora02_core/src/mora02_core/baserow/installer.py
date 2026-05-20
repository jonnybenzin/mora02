"""Schema export and installation utilities for Baserow.

Why this exists:
    Baserow API Tokens can only read/write rows. Listing tables and fields
    requires JWT (user-credentials) auth. So schema introspection is a
    one-shot script run, not a per-request library call.

Usage:
    # Regenerate schema.py — iterates all databases the user has access to:
    python -m mora02_core.baserow.installer

    # Or programmatically:
    from mora02_core.baserow.installer import export_schema
    await export_schema(email="me@example.com", password="...")

Concept ref: docs/system/2605131500_konzept-automatisierung-mora02-v2.md, E3.
"""

import getpass
from datetime import datetime, timezone
from pathlib import Path

import httpx

from mora02_core import auth
from mora02_core._common import get_logger


log = get_logger("mora02_core.baserow.installer")


async def _jwt_login(email: str, password: str) -> str:
    """Authenticate with Baserow user credentials, return JWT access token."""
    url = f"{auth.get('BASEROW_URL', 'http://baserow:80')}/api/user/token-auth/"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, json={"email": email, "password": password})
        if resp.status_code != 200:
            raise RuntimeError(
                f"JWT login failed: {resp.status_code} {resp.text[:200]}"
            )
        return resp.json()["access_token"]


async def _list_applications(jwt: str) -> list[dict]:
    """List all applications (databases + builders) the user has access to."""
    url = f"{auth.get('BASEROW_URL', 'http://baserow:80')}/api/applications/"
    headers = {"Authorization": f"JWT {jwt}"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()


async def _list_tables(jwt: str, database_id: int) -> list[dict]:
    """List all tables in a database (requires JWT)."""
    url = (
        f"{auth.get('BASEROW_URL', 'http://baserow:80')}"
        f"/api/database/tables/database/{database_id}/"
    )
    headers = {"Authorization": f"JWT {jwt}"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()


async def _list_fields(jwt: str, table_id: int) -> list[dict]:
    """List all fields of a table (requires JWT)."""
    url = (
        f"{auth.get('BASEROW_URL', 'http://baserow:80')}"
        f"/api/database/fields/table/{table_id}/"
    )
    headers = {"Authorization": f"JWT {jwt}"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()


def _python_table_name(name: str) -> str:
    """Convert 'Bot Sessions' or 'bot-sessions' to a Python-valid snake_case key."""
    return name.lower().replace(" ", "_").replace("-", "_")


def _py_field_literal(f: dict) -> str:
    """Render a field dict as a Python source-code literal (True/False, not true/false)."""
    name = f["name"].replace('"', '\\"')
    return (
        '{'
        f'"name": "{name}", '
        f'"type": "{f["type"]}", '
        f'"primary": {f["primary"]!r}'
        '}'
    )


async def export_schema(
    *,
    database_id: int | None = None,
    email: str | None = None,
    password: str | None = None,
    output: Path | None = None,
) -> Path:
    """Regenerate ``mora02_core/baserow/schema.py`` from a live Baserow instance.

    Args:
        database_id: which Baserow database to introspect. If None, iterates
            all databases the user has access to. Duplicate table names
            across databases raise.
        email: Baserow user email (prompted if None).
        password: Baserow user password (prompted if None).
        output: target file path (defaults to ``schema.py`` next to this module).

    Returns:
        Path to the written file.
    """
    if not email:
        email = input("Baserow email: ")
    if not password:
        password = getpass.getpass("Baserow password: ")
    if output is None:
        output = Path(__file__).parent / "schema.py"

    log.info("Logging in as %s ...", email)
    jwt = await _jwt_login(email, password)

    # Determine which databases to scan
    if database_id is None:
        log.info("Listing all applications the user has access to ...")
        apps = await _list_applications(jwt)
        database_ids = [a["id"] for a in apps if a.get("type") == "database"]
        log.info("Found %d database(s): %s", len(database_ids), database_ids)
    else:
        database_ids = [database_id]

    table_ids: dict[str, int] = {}
    fields_map: dict[str, list[dict]] = {}
    table_to_db: dict[str, int] = {}

    for db_id in database_ids:
        log.info("Listing tables in database %d ...", db_id)
        tables = await _list_tables(jwt, db_id)
        for t in tables:
            name = _python_table_name(t["name"])
            if name in table_ids:
                raise RuntimeError(
                    f"Duplicate table name {name!r} across databases "
                    f"({table_to_db[name]} and {db_id}). Rename or pass database_id."
                )
            tid = t["id"]
            table_ids[name] = tid
            table_to_db[name] = db_id
            log.info("  reading fields for table '%s' (id=%d, db=%d)", name, tid, db_id)
            fields = await _list_fields(jwt, tid)
            fields_map[name] = [
                {
                    "name": f["name"],
                    "type": f["type"],
                    "primary": f.get("primary", False),
                }
                for f in fields
            ]

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines: list[str] = [
        '"""Schema snapshot for the Mora02 Baserow databases.',
        "",
        f"Generated by mora02_core.baserow.installer.export_schema() at {ts}.",
        "Do NOT edit by hand — re-run the exporter when the schema drifts:",
        "",
        "    python -m mora02_core.baserow.installer",
        '"""',
        "",
        f"DATABASE_IDS: list[int] = {sorted(set(database_ids))!r}",
        "",
        "TABLE_IDS: dict[str, int] = {",
    ]
    for name, tid in sorted(table_ids.items()):
        db = table_to_db[name]
        lines.append(f'    "{name}": {tid},  # db={db}')
    lines.append("}")
    lines.append("")
    lines.append("TABLE_NAMES: dict[int, str] = {v: k for k, v in TABLE_IDS.items()}")
    lines.append("")
    lines.append("FIELDS: dict[str, list[dict]] = {")
    for name in sorted(fields_map):
        lines.append(f'    "{name}": [')
        for f in fields_map[name]:
            lines.append(f"        {_py_field_literal(f)},")
        lines.append("    ],")
    lines.append("}")
    lines.append("")

    output.write_text("\n".join(lines))
    log.info(
        "Wrote schema to %s (%d tables, %d fields total, %d database(s))",
        output,
        len(table_ids),
        sum(len(f) for f in fields_map.values()),
        len(set(database_ids)),
    )
    return output


def install_schema() -> None:
    """Apply schema.py to a Baserow instance.

    Concept: read schema.py, diff against live Baserow, create missing
    tables/fields. Useful for fresh installs and dev environments. Phase-2 work.
    """
    raise NotImplementedError(
        "install_schema() is planned for Phase 2. For now Baserow is the "
        "working source of truth, schema.py is just the snapshot."
    )


def verify_schema() -> None:
    """Check that live Baserow matches schema.py; log warnings on drift."""
    raise NotImplementedError(
        "verify_schema() is planned for Phase 2 — see export_schema() for now."
    )


def main() -> None:
    """CLI entry point for `python -m mora02_core.baserow.installer`."""
    import asyncio
    asyncio.run(export_schema())


if __name__ == "__main__":
    main()
