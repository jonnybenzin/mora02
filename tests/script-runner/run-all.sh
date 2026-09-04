#!/bin/bash
# The script-runner suites. All offline: they build their own data directory
# under /tmp and talk to no service.
#
#   bash tests/script-runner/run-all.sh
#
# main.py could not be imported outside its container until MORA02_SCRIPT_RUNNER_DATA
# existed (it creates /data at import time), which is why 3400 lines had no test
# at all before review run 3.

cd "$(dirname "$0")/../.." || exit 1
export PYTHONPATH="lib/mora02_core/src:apps/script-runner/app${PYTHONPATH:+:$PYTHONPATH}"

FAILED=0
run() {
    echo
    echo "=== $* ==="
    if ! "$@"; then FAILED=$((FAILED + 1)); fi
}

if ! python3 -c "import fastapi" 2>/dev/null; then
    echo "no fastapi in this python — run these where main.py imports, e.g.:"
    echo "  docker run --rm -v /opt/mora02:/repo -w /repo \\"
    echo "    -e PYTHONPATH=lib/mora02_core/src:apps/script-runner/app \\"
    echo "    script-runner:latest bash tests/script-runner/run-all.sh"
    exit 2
fi

run python3 tests/script-runner/test_session_paths.py
run python3 tests/script-runner/test_path_guards.py

echo
if [ "$FAILED" = 0 ]; then echo "all script-runner suites passed"; else echo "$FAILED suite(s) failed"; fi
exit "$FAILED"
