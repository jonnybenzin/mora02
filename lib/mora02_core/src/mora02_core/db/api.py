"""Generic CRUD API for Baserow tables, addressed by table name.

This is the "high-level" facade that new code should prefer over the
function-per-table helpers in ``client.py``. Table names are looked up
in ``schema.TABLE_IDS`` (re-generate via the installer when schema drifts).

Example:
    from mora02_core.db import api

    rows = await api.query("bot_feedback", filter={"Status": "new"})
    new = await api.insert("bot_feedback", {"Type": "bug", "Description": "..."})
    await api.update("bot_feedback", row_id=3, data={"Status": "resolved"})
"""

from typing import Any

import httpx

from mora02_core._common import get_logger
from mora02_core.db import schema
from mora02_core.db.client import _headers, _url

log = get_logger("mora02_core.db.api")


class DbError(RuntimeError):
    """The database refused the call, or could not be reached.

    Distinct from a legitimate `None`, which means "no such row". Both used to
    read as None, so a caller could not tell "the row is not there" from "the
    write was rejected" -- and the pipeline's db steps reported a green run for
    an insert that never happened, while db.query answered an empty list for a
    Baserow that was unreachable, which the scheduled-publish loop read as
    "nothing is due" (review 3, 2026-09-04).
    """



def _table_id(name) -> int:
    """Resolve a table reference to its Baserow table ID.

    Accepts a Python-safe table name (looked up in ``schema.TABLE_IDS``) or a
    numeric table ID passed directly (int or digit string). The numeric form lets
    pipelines address any table — including ad-hoc ones not in the schema map —
    without re-running the installer.
    """
    if isinstance(name, int) or (isinstance(name, str) and name.isdigit()):
        return int(name)
    try:
        return schema.TABLE_IDS[name]
    except KeyError:
        raise KeyError(
            f"Unknown table {name!r}. Known: {sorted(schema.TABLE_IDS)}. "
            "Re-run `python -m mora02_core.db.installer` if the schema drifted."
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
    """Insert a row into the named table. Returns the created row.
    Raises DbError when the database refused it -- an insert either happened or
    it did not, and there is no third answer worth returning."""
    tid = _table_id(table)
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{_url()}/api/database/rows/table/{tid}/?user_field_names=true",
            headers=_headers(), json=data,
        )
        if resp.status_code in (200, 201):
            return resp.json()
        log.warning("insert(%s) failed: %d %s", table, resp.status_code, resp.text[:200])
        raise DbError(f"insert into {table} failed: HTTP {resp.status_code} {resp.text[:200]}")


async def get(
    table: str, row_id: int, *, user_id: str = "default"
) -> dict | None:
    """Read a single row by ID. None when there is no such row.
    Raises DbError when the database could not answer."""
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
            if resp.status_code != 404:
                raise DbError(f"get({table}, {row_id}) failed: HTTP {resp.status_code}")
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
                raise DbError(f"query({table}) failed: HTTP {resp.status_code} {resp.text[:200]}")
            data = resp.json()
            results.extend(data.get("results", []))
            if not all_pages or not data.get("next"):
                break
            cur_page += 1
    return results


async def update(
    table: str, row_id: int, data: dict, *, user_id: str = "default"
) -> dict | None:
    """Patch an existing row. The updated row, or None when there is no such
    row. Raises DbError when the database refused the patch."""
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
        if resp.status_code == 404:
            return None
        raise DbError(f"update({table}, {row_id}) failed: HTTP {resp.status_code} {resp.text[:200]}")


async def delete(
    table: str, row_id: int, *, user_id: str = "default"
) -> bool:
    """Delete a row. True when it went, False when there was no such row.
    Raises DbError when the database refused."""
    tid = _table_id(table)
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.delete(
            f"{_url()}/api/database/rows/table/{tid}/{row_id}/",
            headers=_headers(),
        )
        if resp.status_code == 204:
            return True
        if resp.status_code == 404:
            return False
        raise DbError(f"delete({table}, {row_id}) failed: HTTP {resp.status_code}")


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
        raise DbError(f"list_fields({table}) failed: HTTP {resp.status_code}")
