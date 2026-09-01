#!/bin/bash
# Run the pipeline test suites - the cheap ones by default, the costly ones only
# when asked for.
#
#   bash tests/pipeline/run-all.sh              # everything free and fast
#   bash tests/pipeline/run-all.sh --ui         # plus the browser suite
#   bash tests/pipeline/run-all.sh --agents     # plus the agent gate-discipline suite
#   bash tests/pipeline/run-all.sh --vocab 1,2  # plus vocabulary tiers 1 and 2
#   bash tests/pipeline/run-all.sh --all        # free suites + browser + agents + tier 1
#
# Why a launcher at all: on 29 August 2026 these ten suites were run one at a
# time from memory, in an order nobody had written down. A suite whose entry
# points live only in someone's head is a suite that stops being run - and then
# the defects it was built to catch come back quietly, which is the exact failure
# mode this whole set exists to prevent.
#
# What the suites need:
#   - a running stack (script-runner on 8096); everything talks to real services
#   - the browser suites additionally need Playwright + Chromium and nginx on 8092
#   - the db ops in the vocabulary suite need MORA02_TEST_TABLE set to a scratch table
#   - the vocabulary suite spends real resources from tier 2 upward: GPU minutes,
#     then money, then messages that reach a phone. Nothing above tier 1 runs
#     unless its number is named, and publish.linkedin needs --i-mean-it on top.
#
# Exit code is the number of suites that failed, so CI or a wrapper can act on it.

cd "$(dirname "$0")/../.." || exit 1

RUNNER_URL="${SCRIPT_RUNNER_URL:-http://127.0.0.1:8096}"
WITH_UI=0
WITH_AGENTS=0
VOCAB_TIERS=""

while [ $# -gt 0 ]; do
    case "$1" in
        --ui)     WITH_UI=1 ;;
        --agents) WITH_AGENTS=1 ;;
        --vocab)  VOCAB_TIERS="$2"; shift ;;
        --all)    WITH_UI=1; WITH_AGENTS=1; VOCAB_TIERS="1" ;;
        -h|--help)
            sed -n '2,28p' "$0"; exit 0 ;;
        *) echo "unknown option: $1"; exit 2 ;;
    esac
    shift
done

if ! curl -s -o /dev/null --max-time 5 "$RUNNER_URL/health"; then
    echo "script-runner is not answering at $RUNNER_URL - start the stack first."
    exit 2
fi

FAILED=0
SUMMARY=""

run_suite() {
    local name="$1"; shift
    echo
    echo "================================================================"
    echo " $name"
    echo "================================================================"
    if python3 "$@"; then
        SUMMARY="${SUMMARY}  ok    ${name}\n"
    else
        SUMMARY="${SUMMARY}  FAIL  ${name}\n"
        FAILED=$((FAILED + 1))
    fi
}

# Free and fast. In the order the test plan works through them: does a value
# survive, does a failure get reported, does the wiring hold, do the gates and
# the partial re-runs behave, does the library refuse what it should, and do the
# odd combinations stay decided rather than accidental.
run_suite "passthrough - does a value survive the way in"  tests/pipeline/test_passthrough.py
run_suite "errorpaths - does a failure reach a human"      tests/pipeline/test_errorpaths.py
run_suite "wiring - does a value reach the right step"     tests/pipeline/test_wiring.py
run_suite "gates - do human decisions land where they belong" tests/pipeline/test_gates.py
run_suite "rerun - is a partial re-run trustworthy"        tests/pipeline/test_rerun.py
run_suite "library - does the flow library refuse the broken" tests/pipeline/test_library.py
run_suite "edgecases - the combinations nobody would build" tests/pipeline/test_edgecases.py
run_suite "truncation - does every cut announce itself"    tests/pipeline/test_truncation.py

# The agent layer's free half. The handshake suite talks only to our own /mcp
# endpoint: no model, no gateway, nothing spent - and it is the tripwire under a
# hand-written MCP server, so it belongs in every pass.
run_suite "mcp handshake - does our server still speak what openclaw sends" \
    tests/agents/test_mcp_handshake.py

if [ "$WITH_UI" = "1" ]; then
    run_suite "builder UI - the browser half of the builder" tests/pipeline/test_builder_ui.py
    run_suite "wiki VOCABULARY - the vocabulary as a table"   tests/pipeline/test_wiki_vocab.py
fi

if [ -n "$VOCAB_TIERS" ]; then
    run_suite "vocabulary - every op once, in a chain (tiers $VOCAB_TIERS)" \
        tests/pipeline/test_vocabulary.py --tier "$VOCAB_TIERS"
fi

# Behind a flag, for two reasons. It starts a real run (one local completion,
# three agent turns, ~2 minutes), and its verdict depends on how a MODEL behaves
# under pressure - so it can go red on a day when nothing in this repo changed.
# A suite that fails for reasons outside the code, sitting in the default pass,
# is how a whole test canon stops being believed.
if [ "$WITH_AGENTS" = "1" ]; then
    run_suite "gate discipline - the agent starts a flow but cannot open its gate" \
        tests/agents/test_gate_discipline.py
fi

echo
echo "================================================================"
printf " %s" "$(date '+%Y-%m-%d %H:%M:%S')"
echo
echo "================================================================"
printf "%b" "$SUMMARY"
if [ "$FAILED" -eq 0 ]; then
    echo
    echo " all suites green"
else
    echo
    echo " $FAILED suite(s) failed"
fi
if [ "$WITH_UI" != "1" ] || [ "$WITH_AGENTS" != "1" ] || [ -z "$VOCAB_TIERS" ]; then
    echo
    echo " not run in this pass:"
    [ "$WITH_UI" != "1" ] && echo "   the browser suite      (--ui)"
    [ "$WITH_AGENTS" != "1" ] && echo "   the gate-discipline suite (--agents)"
    [ -z "$VOCAB_TIERS" ] && echo "   the vocabulary suite   (--vocab 1  … up to 5, see its docstring)"
fi
exit "$FAILED"
