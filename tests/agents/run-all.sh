#!/bin/bash
# Run the agent-layer test suites - the free ones by default, the ones that
# spend a model's time or touch the gateway only when asked for.
#
#   bash tests/agents/run-all.sh             # offline + read-only against script-runner
#   bash tests/agents/run-all.sh --deploy    # plus a real rollout round trip (T6, T10)
#   bash tests/agents/run-all.sh --model     # plus the suites that run a model turn
#   bash tests/agents/run-all.sh --all       # everything
#
# Why a launcher: tests/pipeline/ got one on 29 August 2026 after its ten suites
# had been run from memory in an order nobody had written down. tests/agents/
# reached five suites the same way. Same fix, same shape, same exit code
# convention: the number of suites that failed.
#
# What the suites need:
#   - the offline suites (builder_store, source_check, mcp_input) need no
#     service; the latter two need fastapi importable
#   - the rest talk to script-runner on 8096; --deploy also to the gateway
#     container through it, and leaves a folder in agents/instances/.trash/
#   - --model runs a local model for minutes per suite (gate_discipline starts a
#     real flow and holds at a gate; briefing holds a scripted conversation)

cd "$(dirname "$0")/../.." || exit 1

export PYTHONPATH="lib/mora02_core/src:apps/script-runner/app${PYTHONPATH:+:$PYTHONPATH}"
WITH_DEPLOY=0
WITH_MODEL=0

while [ $# -gt 0 ]; do
    case "$1" in
        --deploy) WITH_DEPLOY=1 ;;
        --model)  WITH_MODEL=1 ;;
        --all)    WITH_DEPLOY=1; WITH_MODEL=1 ;;
        -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
        *) echo "unknown flag: $1" >&2; exit 2 ;;
    esac
    shift
done

FAILED=0
SKIPPED=0
run() {
    echo
    echo "=== $* ==="
    if ! "$@"; then FAILED=$((FAILED + 1)); fi
}

# free and offline
run python3 tests/agents/test_builder_store.py
# source_check imports mcp_tools, which imports FastAPI. The host python has no
# FastAPI (it is a dependency of the container, not of the machine), so on the
# host this suite is skipped and SAID to be skipped -- the alternative, a red
# suite for a missing library, would train everyone to ignore red.
if python3 -c "import fastapi" 2>/dev/null; then
    run python3 tests/agents/test_source_check.py
    run python3 tests/agents/test_mcp_input.py
else
    echo; echo "=== test_source_check.py + test_mcp_input.py: skipped (no fastapi in this python; run them where mcp_tools imports, e.g. inside the script-runner image) ==="
    SKIPPED=$((SKIPPED + 2))
fi

# free, needs the service
run python3 tests/agents/test_mcp_handshake.py
run python3 tests/agents/test_roster.py
if [ "$WITH_DEPLOY" = 1 ]; then
    run python3 tests/agents/test_builder_api.py --deploy
else
    run python3 tests/agents/test_builder_api.py
fi

# spends a model's time
if [ "$WITH_MODEL" = 1 ]; then
    run python3 tests/agents/test_gate_discipline.py
    run python3 tests/agents/test_briefing.py
fi

echo
if [ "$FAILED" = 0 ]; then echo "all agent suites passed ($SKIPPED skipped)"; else echo "$FAILED suite(s) failed ($SKIPPED skipped)"; fi
exit "$FAILED"
