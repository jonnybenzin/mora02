#!/bin/bash
# Lint every Python file in the repository with ruff, using the rules in
# ruff.toml at the root. Exit code is ruff's: 0 means clean.
#
#   bash scripts/lint.sh          # report
#   bash scripts/lint.sh --fix    # apply the fixes ruff marks as safe
#
# ruff is a single binary and not a Python dependency of any service here, so
# it is installed per user, not per image:  pipx install ruff
# (pipx puts it in ~/.local/bin, which the pre-commit hook also looks in.)

cd "$(dirname "$0")/.." || exit 1

RUFF="$(command -v ruff 2>/dev/null || true)"
[ -z "$RUFF" ] && [ -x "$HOME/.local/bin/ruff" ] && RUFF="$HOME/.local/bin/ruff"
if [ -z "$RUFF" ]; then
    echo "lint: ruff is not installed - install it with 'pipx install ruff'." >&2
    exit 2
fi

exec "$RUFF" check "$@" .
