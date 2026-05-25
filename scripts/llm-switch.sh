#!/bin/bash
# ============================================================================
# Mora02 LLM Profile Switcher
# ============================================================================
# Processes requests from /opt/mora02/llm-switch/requests/*.json
# Validates profile name against a hardcoded whitelist (security anchor).
# Runs `docker compose --profile <name> up -d llama-<name>`.
# Writes result to /opt/mora02/llm-switch/responses/<request_id>.json.
#
# Triggered by systemd (llm-switch.path + llm-switch.service).
# Runs as root — required for docker daemon and nvidia-smi access.
#
# Flow per request:
#   1. parse + validate request (whitelist enforced)
#   2. VRAM pre-flight check (reject cleanly if insufficient, no containers touched)
#   3. remember previous profile for auto-rollback
#   4. docker rm -f llama-server
#   5. docker compose up new profile
#   6. wait for healthcheck
#      - healthy → write current.json, write ok=true response
#      - unhealthy → remove zombie, rollback to previous profile, write ok=false
# ============================================================================

set -euo pipefail

SWITCH_DIR=/opt/mora02/llm-switch
REQUESTS_DIR="$SWITCH_DIR/requests"
RESPONSES_DIR="$SWITCH_DIR/responses"
CURRENT_STATE_FILE="$SWITCH_DIR/current.json"
COMPOSE_DIR=/opt/mora02/docker
MAX_HEALTH_WAIT=240          # seconds to wait for healthcheck after start
                             # (cold-load of a 24B gguf from disk can take >2min)
VRAM_SAFETY_MARGIN_MB=1500   # leave this much headroom

# --- Whitelist: the security anchor -----------------------------------------
# Any profile name NOT in this map is rejected.
declare -A VALID_PROFILES=(
  [qwen3-14b]=1
  [qwen3-8b]=1
  [qwen25-7b]=1
  [qwen25-coder]=1
  [nous-hermes]=1
  [magistral]=1
)

# --- VRAM requirements per profile (MiB) -----------------------------------
# Tuned from actual nvidia-smi measurements on 2026-04-11:
#   qwen3-14b real:  14238 MiB
#   magistral real:  19338 MiB (log: model=13302 + KV=5120 + overhead)
# Others extrapolated from the same architecture class.
# Re-tune if llama.cpp version or ctx-size changes in docker-compose.yml.
declare -A VRAM_REQUIRED_MB=(
  [qwen3-14b]=15000
  [qwen3-8b]=9500
  [qwen25-7b]=9000
  [qwen25-coder]=15000
  [nous-hermes]=9000
  [magistral]=20000
)

# --- Helpers ----------------------------------------------------------------

log() { echo "[$(date -Iseconds)] $*"; }

write_response() {
    local request_id="$1"
    local ok="$2"         # "true" or "false"
    local profile="$3"
    local message="$4"
    local tmp="${RESPONSES_DIR}/.${request_id}.tmp"
    local final="${RESPONSES_DIR}/${request_id}.json"

    jq -n \
        --arg rid "$request_id" \
        --argjson ok "$ok" \
        --arg prof "$profile" \
        --arg msg "$message" \
        '{request_id: $rid, ok: $ok, profile: $prof, message: $msg, timestamp: (now | todate)}' \
        > "$tmp"
    mv "$tmp" "$final"
}

# Write the current-profile state file atomically.
write_current_state() {
    local profile="$1"
    local state_tmp="${SWITCH_DIR}/.current.tmp"
    jq -n --arg prof "$profile" \
        '{profile: $prof, timestamp: (now | todate)}' \
        > "$state_tmp"
    mv "$state_tmp" "$CURRENT_STATE_FILE"
}

# Read the currently-recorded profile from current.json, or empty string.
read_current_profile() {
    if [[ ! -f "$CURRENT_STATE_FILE" ]]; then
        echo ""
        return
    fi
    jq -r '.profile // empty' "$CURRENT_STATE_FILE" 2>/dev/null || echo ""
}

# Query GPU free memory in MiB. Outputs a single integer on stdout, or empty
# on failure (caller decides how to treat that).
query_vram_free_mb() {
    nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits 2>/dev/null \
        | head -n 1 | tr -d ' '
}

# Query VRAM currently held by any process with "llama-server" in its name.
# Outputs an integer (0 if none).
query_llama_vram_mb() {
    nvidia-smi --query-compute-apps=used_memory,process_name \
        --format=csv,noheader,nounits 2>/dev/null \
        | awk -F', *' 'tolower($2) ~ /llama-server/ { sum += $1 } END { print sum+0 }'
}

# Pre-flight VRAM check. Returns 0 if switch is OK, 1 if not enough VRAM.
# On rejection, echoes a human-readable reason on stdout.
check_vram_availability() {
    local profile="$1"
    local required="${VRAM_REQUIRED_MB[$profile]:-16000}"

    local free_mb
    free_mb="$(query_vram_free_mb)"
    if [[ -z "$free_mb" || ! "$free_mb" =~ ^[0-9]+$ ]]; then
        # nvidia-smi failed — fail open with a warning, don't block the switch
        log "WARN: nvidia-smi unavailable, skipping VRAM pre-check"
        return 0
    fi

    local llama_mb
    llama_mb="$(query_llama_vram_mb)"
    [[ "$llama_mb" =~ ^[0-9]+$ ]] || llama_mb=0

    local effective=$(( free_mb + llama_mb ))
    local needed=$(( required + VRAM_SAFETY_MARGIN_MB ))

    log "VRAM check: free=${free_mb}MB + llama=${llama_mb}MB = effective=${effective}MB, profile needs=${required}MB + safety=${VRAM_SAFETY_MARGIN_MB}MB"

    if (( effective < needed )); then
        echo "insufficient VRAM: need ${required} MB + ${VRAM_SAFETY_MARGIN_MB} MB safety = ${needed} MB, have ${effective} MB effective (free ${free_mb} + stoppable llama ${llama_mb}). Free GPU memory first (Dashboard button) or stop other GPU containers."
        return 1
    fi
    return 0
}

# Start a profile via docker compose. Returns 0 on success (container created,
# not necessarily healthy).
start_profile_container() {
    local profile="$1"
    ( cd "$COMPOSE_DIR" && docker compose --profile "$profile" up -d "llama-$profile" 2>&1 )
}

# Wait for llama-server healthcheck to turn "healthy". Echoes the final status.
wait_for_healthy() {
    local waited=0
    local status="starting"
    while (( waited < MAX_HEALTH_WAIT )); do
        status=$(docker inspect --format='{{.State.Health.Status}}' llama-server 2>/dev/null || echo "unknown")
        if [[ "$status" == "healthy" ]]; then
            break
        fi
        sleep 2
        waited=$((waited + 2))
    done
    echo "$status $waited"
}

# Attempt to restore a previous profile after a failed switch.
# Returns 0 on successful rollback, 1 otherwise.
rollback_to() {
    local prev="$1"
    if [[ -z "$prev" ]]; then
        log "rollback: no previous profile known"
        return 1
    fi
    if [[ -z "${VALID_PROFILES[$prev]:-}" ]]; then
        log "rollback: previous profile '$prev' not in whitelist"
        return 1
    fi

    log "rollback: starting $prev"
    docker rm -f llama-server >/dev/null 2>&1 || true
    if ! start_profile_container "$prev"; then
        log "rollback: docker compose up failed for $prev"
        return 1
    fi

    local result status waited
    result="$(wait_for_healthy)"
    status="${result% *}"
    waited="${result##* }"

    if [[ "$status" == "healthy" ]]; then
        log "rollback: $prev healthy after ${waited}s"
        write_current_state "$prev"
        return 0
    else
        log "rollback: $prev still $status after ${waited}s"
        return 1
    fi
}

process_request() {
    local req_file="$1"
    local request_id profile prev_profile

    # Parse request_id
    if ! request_id=$(jq -r '.request_id // empty' "$req_file" 2>/dev/null); then
        log "ERROR: invalid JSON in $req_file, discarding"
        rm -f "$req_file"
        return
    fi
    if [[ -z "$request_id" ]]; then
        log "ERROR: missing request_id in $req_file, discarding"
        rm -f "$req_file"
        return
    fi
    if ! [[ "$request_id" =~ ^[A-Za-z0-9_-]+$ ]]; then
        log "ERROR: invalid request_id format: $request_id"
        rm -f "$req_file"
        return
    fi

    profile=$(jq -r '.profile // empty' "$req_file")

    # --- WHITELIST CHECK ---
    if [[ -z "${VALID_PROFILES[$profile]:-}" ]]; then
        log "ERROR: invalid profile '$profile' for request $request_id"
        write_response "$request_id" "false" "$profile" "invalid profile"
        rm -f "$req_file"
        return
    fi

    # --- VRAM PRE-FLIGHT CHECK ---
    local vram_reason
    if ! vram_reason="$(check_vram_availability "$profile")"; then
        log "ERROR: $vram_reason"
        write_response "$request_id" "false" "$profile" "$vram_reason"
        rm -f "$req_file"
        return
    fi

    # --- Remember previous profile for rollback ---
    prev_profile="$(read_current_profile)"
    log "switching to '$profile' (prev='$prev_profile', request $request_id)"

    # --- Remove any existing llama-server container (from any profile) ---
    docker rm -f llama-server >/dev/null 2>&1 || true

    # --- Start the new profile ---
    if ! start_profile_container "$profile"; then
        log "ERROR: docker compose up failed for profile $profile"
        # Attempt rollback if we had a previous profile
        if [[ -n "$prev_profile" && "$prev_profile" != "$profile" ]]; then
            if rollback_to "$prev_profile"; then
                write_response "$request_id" "false" "$profile" "docker compose failed, rolled back to $prev_profile"
            else
                write_response "$request_id" "false" "$profile" "docker compose failed, rollback to $prev_profile also failed"
            fi
        else
            write_response "$request_id" "false" "$profile" "docker compose failed, no previous profile to roll back to"
        fi
        rm -f "$req_file"
        return
    fi

    # --- Wait for healthcheck ---
    local result status waited
    result="$(wait_for_healthy)"
    status="${result% *}"
    waited="${result##* }"

    if [[ "$status" == "healthy" ]]; then
        log "profile $profile healthy after ${waited}s"
        write_current_state "$profile"
        write_response "$request_id" "true" "$profile" "ready after ${waited}s"
        rm -f "$req_file"
        return
    fi

    # --- Unhealthy path: zombie cleanup + rollback ---
    log "profile $profile NOT healthy after ${waited}s (status=$status), removing zombie"
    docker rm -f llama-server >/dev/null 2>&1 || true

    if [[ -n "$prev_profile" && "$prev_profile" != "$profile" ]]; then
        if rollback_to "$prev_profile"; then
            write_response "$request_id" "false" "$profile" "health=$status after ${waited}s, rolled back to $prev_profile"
        else
            write_response "$request_id" "false" "$profile" "health=$status after ${waited}s, rollback to $prev_profile failed — NO LLM RUNNING"
        fi
    else
        write_response "$request_id" "false" "$profile" "health=$status after ${waited}s, no previous profile to roll back to — NO LLM RUNNING"
    fi

    rm -f "$req_file"
}

# --- Main -------------------------------------------------------------------

mkdir -p "$REQUESTS_DIR" "$RESPONSES_DIR"

shopt -s nullglob
for req_file in "$REQUESTS_DIR"/*.json; do
    process_request "$req_file"
done

# Cleanup responses older than 1 hour (prevent directory from growing forever)
find "$RESPONSES_DIR" -name "*.json" -mmin +60 -delete 2>/dev/null || true
