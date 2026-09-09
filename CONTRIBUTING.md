# Contributing

This repository is a workshop log: one person's locally hosted creative
factory, published to be read and learned from. It is not built to be
deployed elsewhere (see "Can you run it?" in the README), so contributions
are welcome mostly in the form of questions, corrections and ideas.

## Ways to contribute

- **Questions and ideas**: open an issue. English or German both work.
- **Bug reports**: open an issue with what you did, what you expected and
  what happened. Log excerpts help; secrets never (the `.env` file is the
  one thing that must not appear anywhere).
- **Security findings**: see [SECURITY.md](SECURITY.md), not an issue.
- **Pull requests**: small and focused. Anything larger, open an issue first
  so the direction is agreed before the work.

## Standards for code changes

- Code comments and identifiers are English.
- Python passes `ruff` with the rules in `ruff.toml` (`scripts/lint.sh`).
- The pre-commit hooks in `.githooks/` must pass; enable them once with
  `git config core.hooksPath .githooks`.
- Major new functionality comes with tests. The suites live under `tests/`
  and `lib/mora02_core/tests/`; each directory has a `run-all.sh` that says
  which suites need the running Docker stack and which do not.
- Commit messages: a subject of at most 60 characters in the form
  `<area>: what changes`, the why in the body.
- `docker/docker-compose.yml` and `docker/.env` are edited by the
  maintainer only; propose changes to them as a diff in the PR description.
