# Changelog

Human-readable summary per tagged version. Commit messages carry the detail
and the why; this file names the milestones and any security fix that
users of this repository should know about. Versions follow calendar
versioning: `vYYYY.MM.N`, N counting releases within the month.

## Unreleased

**Security**
- Pilot auth stage 1: every API call needs the shared token from
  `MORA02_PILOT_TOKEN` (`Authorization: Bearer …`). The UI asks for it once
  and keeps it in the browser; the script-runner sends it on its callbacks;
  `/health` stays open for the compose healthcheck. Pilot was the one
  unauthenticated front door to the stack, including the proxy to the
  script-runner.

## v2026.09.1 — 2026-09-09

The container audit and the first OpenSSF pass.

**Security**
- Penpot 2.12.1 → 2.17.2. Closes CVE-2026-44986 (pre-authenticated
  account takeover via invitation tokens) and two stored-XSS advisories.
- 31 known vulnerabilities in pinned Python dependencies closed by raising
  the pins: Pillow 12.3.0, python-multipart 0.0.32, starlette 1.6.0,
  fastapi 0.141.1 (`deps: raise pinned python packages`).
- Pilot, first review of `app.py`: explicit CORS origin list instead of
  `*`; the file-delete route no longer removes directories and uses a
  real containment check; upload file names go through the path rule;
  post-media uploads are limited to media types (an uploaded `.html` was
  served from the UI's own origin); expand/upscale sources are limited to
  the asset server (was a readable SSRF); upload size ceiling; five
  unused routes removed.

**Stack**
- Dify, ActivePieces, Weaviate, Ollama and their helpers retired: eleven
  containers fewer, 40 → 28 services. Redis stays for Penpot.
- Every third-party image pinned to a version; `scripts/docker/image-check.py`
  reports what the registries have newer and which build runs locally.
- Baserow 1.26.1 → 2.3.3.

**Pilot**
- Monthly cost badge no longer counts every paid call twice; cost bookings
  after the first of a month no longer fail on Baserow's decimal strings;
  a lock serialises the ledger update.
- Chat sessions no longer break silently after ~50 messages (history window
  now starts on a user turn); model errors surface in the stream; STOP
  still books the partial answer.
- Post list, chat statistics line and style-pack folder picker work again.
- Page styles moved out of the page fragments into `css/pages.css`.

**Repository**
- SECURITY.md, CONTRIBUTING.md, README rewritten to the current stack.
- `.env.example` generated from the compose variable references.
- CI stage 1: ruff, stack-free library tests, pip-audit on every push.
