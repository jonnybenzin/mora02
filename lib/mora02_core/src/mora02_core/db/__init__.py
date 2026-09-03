"""mora02_core.db — Baserow client + schema + high-level API.

Phase 1.2a: low-level client extracted from apps/pilot/baserow_client.py.
Phase 1.2b: schema export via installer.export_schema() + schema.py snapshot.
Phase 1.2c: high-level CRUD API in mora02_core.db.api (insert/get/query/update/delete).

Recommended for new code:

    from mora02_core.db import api
    rows = await api.query("bot_feedback", filter={"Status": "new"})

The functions below remain for backward compatibility with the original
Pilot client until apps are migrated.
"""

from mora02_core.db import api, schema
from mora02_core.db.client import (
    # low-level helpers — for callers that do direct httpx requests
    headers,
    url,
    # sessions
    write_session,
    read_last_sessions,
    read_all_sessions,
    # context
    read_context,
    write_context,
    # known issues
    read_known_issues,
    # feedback
    write_feedback,
    list_feedback,
    update_feedback,
    # buckets
    save_bucket,
    list_buckets,
    delete_bucket,
    # style packs
    save_style_pack,
    list_style_packs,
    get_style_pack,
    get_style_pack_by_name,
    update_style_pack,
    delete_style_pack,
    # posts (sm_content)
    list_posts,
    create_post,
    update_post,
    # formatters
    format_sessions_context,
    format_known_issues,
    format_context_table,
)

__all__ = [
    "headers",
    "url",
    "write_session",
    "read_last_sessions",
    "read_all_sessions",
    "read_context",
    "write_context",
    "read_known_issues",
    "write_feedback",
    "list_feedback",
    "update_feedback",
    "save_bucket",
    "list_buckets",
    "delete_bucket",
    "save_style_pack",
    "list_style_packs",
    "get_style_pack",
    "get_style_pack_by_name",
    "update_style_pack",
    "delete_style_pack",
    "list_posts",
    "create_post",
    "update_post",
    "format_sessions_context",
    "format_known_issues",
    "format_context_table",
]
