"""Generic CRUD API for Baserow tables, addressed by table name.

This is the "high-level" facade that new code should prefer over the
function-per-table helpers in ``client.py``. Table names are looked up
in ``schema.TABLE_IDS`` (re-generate via the installer when schema drifts).

Example:
    from mora02_core.baserow import api

    rows = await api.query("bot_personas", filter={"active": True})
    new = await api.insert("bot_feedback", {"Type": "bug", "Description": "..."})
    await api.update("bot_personas", row_id=3, data={"active": False})
"""

from typing import Any

import httpx

from mora02_core._common import get_logger
from mora02_core.baserow import schema
from mora02_core.baserow.client import _headers, _url

log = get_logger("mora02_core.baserow.api")


def _table_id(name: str) -> int:
    """Look up a Baserow table ID by Python-safe table name."""
    try:
        return schema.TABLE_IDS[name]
    except KeyError:
        raise KeyError(
            f"Unknown table {name!r}. Known: {sorted(schema.TABLE_IDS)}. "
            "Re-run `python -m mora02_core.baserow.installer` if the schema drifted."
        ) from None


def _filter_params(filter: dict[str, Any] | None) -> dict[str, str]:
    """Translate a logical filter dict to Baserow ``filter__<field>__<op>`` params.

    Default operator: ``__equal`` for non-bool, ``__boolean`` for bool values
    (Baserow's ``equal`` doesn't match boolean fields). Override per-key by
    appending ``__op``: ``{"created_at__date_after": "2026-05-01"}``.
    """
    if not filter:
        return {}
    out: dict[str, str] = {}
    for k, v in filter.items():
        has_op = "__" in k
        if isinstance(v, bool):
            key = f"filter__{k}" if has_op else f"filter__{k}__boolean"
            out[key] = "true" if v else "false"
        else:
            key = f"filter__{k}" if has_op else f"filter__{k}__equal"
            out[key] = str(v)
    return out


# ----------------------------------------------------------------------------
# CRUD
# ----------------------------------------------------------------------------

async def insert(
    table: str, data: dict, *, user_id: str = "default"
) -> dict | None:
    """Insert a row into the named table. Returns the created row, or None."""
    tid = _table_id(table)
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{_url()}/api/database/rows/table/{tid}/?user_field_names=true",
            headers=_headers(), json=data,
        )
        if resp.status_code in (200, 201):
            return resp.json()
        log.warning("insert(%s) failed: %d %s", table, resp.status_code, resp.text[:200])
        return None


async def get(
    table: str, row_id: int, *, user_id: str = "default"
) -> dict | None:
    """Read a single row by ID. Returns None if not found."""
    tid = _table_id(table)
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{_url()}/api/database/rows/table/{tid}/{row_id}/?user_field_names=true",
            headers=_headers(),
        )
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code != 404:
            log.warning("get(%s, %d) failed: %d %s", table, row_id, resp.status_code, resp.text[:200])
        return None


async def query(
    table: str,
    *,
    filter: dict[str, Any] | None = None,
    order_by: str | None = None,
    size: int = 50,
    page: int = 1,
    all_pages: bool = False,
    user_id: str = "default",
) -> list[dict]:
    """Query rows from the named table.

    Args:
        filter: see :func:`_filter_params` for syntax.
        order_by: Baserow order string, e.g. ``"-created_at"`` (``-`` = desc).
        size: rows per page (max 200 in Baserow).
        page: starting page (1-based).
        all_pages: if True, paginate through all pages, return combined list.
        user_id: threaded through for multi-user (currently unused).
    """
    tid = _table_id(table)
    params: dict[str, str] = {"user_field_names": "true", "size": str(size)}
    if order_by:
        params["order_by"] = order_by
    params.update(_filter_params(filter))

    results: list[dict] = []
    async with httpx.AsyncClient(timeout=10.0) as client:
        cur_page = page
        while True:
            params["page"] = str(cur_page)
            resp = await client.get(
                f"{_url()}/api/database/rows/table/{tid}/",
                headers=_headers(), params=params,
            )
            if resp.status_code != 200:
                log.warning("query(%s) failed: %d %s", table, resp.status_code, resp.text[:200])
                break
            data = resp.json()
            results.extend(data.get("results", []))
            if not all_pages or not data.get("next"):
                break
            cur_page += 1
    return results


async def update(
    table: str, row_id: int, data: dict, *, user_id: str = "default"
) -> dict | None:
    """Patch an existing row. Returns the updated row or None on failure."""
    tid = _table_id(table)
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.patch(
            f"{_url()}/api/database/rows/table/{tid}/{row_id}/?user_field_names=true",
            headers=_headers(), json=data,
        )
        if resp.status_code == 200:
            return resp.json()
        log.warning(
            "update(%s, %d) failed: %d %s", table, row_id, resp.status_code, resp.text[:200],
        )
        return None


async def delete(
    table: str, row_id: int, *, user_id: str = "default"
) -> bool:
    """Delete a row. Returns True on 204."""
    tid = _table_id(table)
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.delete(
            f"{_url()}/api/database/rows/table/{tid}/{row_id}/",
            headers=_headers(),
        )
        return resp.status_code == 204


async def list_fields(table: str, *, user_id: str = "default") -> list[dict]:
    """Return live field definitions for the named table.

    Each entry has keys ``id``, ``name``, ``type``. Read-only — for full
    schema export use the installer module instead.
    """
    tid = _table_id(table)
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{_url()}/api/database/fields/table/{tid}/",
            headers=_headers(),
        )
        if resp.status_code == 200:
            return resp.json()
        log.warning("list_fields(%s) failed: %d %s", table, resp.status_code, resp.text[:200])
        return []
