# Security Policy

mora02 is a single-maintainer personal lab, not a product. It still takes
security reports seriously: the stack holds API keys, database passwords
and a home-network attack surface, and a report that reaches the maintainer
gets fixed.

## Reporting a vulnerability

Please do **not** open a public issue for anything security-relevant.

- Preferred: GitHub's private vulnerability reporting for this repository
  ("Security" tab -> "Report a vulnerability"). The report is visible only
  to the maintainer.
- Anything that is clearly not sensitive (a dependency bump, a hardening
  suggestion) can go into a normal issue.

You will get an acknowledgement within 14 days. Fixes for medium or higher
severity are the top priority and are published as normal commits on `main`;
there are no separate security releases. If a fix needs a change on your
side (rotate a key, recreate a container), the commit message says so.

## Scope

- Everything under `apps/`, `lib/`, `scripts/` and `docker/` in this
  repository.
- Third-party images the stack runs are tracked, not patched here: every
  image is pinned to a version in `docker/docker-compose.yml`, and
  `scripts/docker/image-check.py` reports what the registries have newer.
  A vulnerability in one of those goes to the upstream project; a report
  here is still welcome so the pin can be raised.

## What the repository does to protect itself

- Secrets live only in `docker/.env`, which is never committed; the
  pre-commit hook runs gitleaks on every staged change.
- A boundary guard refuses host-specific artefacts (paths, private
  addresses, systemd units) in this public repository.
- ruff runs on every staged Python file.
- Services bind to `127.0.0.1` unless they must be reached from the LAN.
