# mora02_core

Shared Python library for the [Mora02](../../README.md) creative AI factory.

Atomic building blocks: env loader, structured logger, HTTP retry, unified
`Asset` dataclass. Future modules will provide Baserow client, LLM router,
ComfyUI client. Consumed by `apps/pilot`, `apps/script-runner`,
`apps/knowledge-api` via `pip install` at container-build time.

## Install (in container Dockerfile)

```dockerfile
COPY lib/mora02_core /tmp/mora02_core
RUN pip install /tmp/mora02_core
```

## Local dev

```bash
cd lib/mora02_core
pip install -e ".[dev]"
pytest
```

## Modules

| Module | Status | Purpose |
|---|---|---|
| `mora02_core.auth` | ✅ | `.env` loader, `require()` / `get()` for secrets |
| `mora02_core.assets` | ✅ | Unified `Asset` dataclass with `user_id` |
| `mora02_core._common` | ✅ | Structured logger, HTTP retry |
| `mora02_core.baserow` | 🚧 | CRUD with table-names instead of IDs |
| `mora02_core.llm` | 📋 | Multi-backend LLM router |
| `mora02_core.comfyui` | 📋 | Workflow runner |

## Design principles

- **user_id everywhere** — every function takes a `user_id` param even if it's always `"default"` today (E7, multi-user prep)
- **Asset dataclass over dict-chaos** — single shape for any generated artifact
- **fail-fast on missing env** — `auth.require()` raises with a clear error instead of returning `None` or `""`
- **no print()** — use the structured logger from `_common`

## Status

Pre-1.0. API not stable. See `/opt/mora02/docs/system/2605131500_konzept-automatisierung-mora02-v2.md`.
