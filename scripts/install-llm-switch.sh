#!/bin/bash
# ============================================================================
# Mora02 LLM Switcher — One-time Installation
# ============================================================================
# Installs systemd units for host-side LLM profile switching.
# Must be run as root (sudo).
#
# What it does:
#   1. Validates dependencies (jq, docker, docker compose, systemctl)
#   2. Creates /opt/mora02/llm-switch/{requests,responses}/
#   3. Writes /etc/systemd/system/llm-switch.path
#   4. Writes /etc/systemd/system/llm-switch.service
#   5. Reloads systemd, enables & starts the path unit
#
# Idempotent: safe to re-run.
# ============================================================================

set -euo pipefail

# --- Preconditions ----------------------------------------------------------

if [[ $EUID -ne 0 ]]; then
    echo "ERROR: this script must be run as root (use sudo)" >&2
    exit 1
fi

INSTALL_ROOT=/opt/mora02
SWITCH_DIR="$INSTALL_ROOT/llm-switch"
REQUESTS_DIR="$SWITCH_DIR/requests"
RESPONSES_DIR="$SWITCH_DIR/responses"
LLM_SCRIPT="$INSTALL_ROOT/scripts/llm-switch.sh"
SYSTEMD_DIR=/etc/systemd/system
PATH_UNIT="$SYSTEMD_DIR/llm-switch.path"
SERVICE_UNIT="$SYSTEMD_DIR/llm-switch.service"

echo "==> Mora02 LLM Switcher Installer"
echo

# --- Dependency check -------------------------------------------------------

echo "==> [1/6] Checking dependencies..."
missing=()
for cmd in jq docker systemctl find; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        missing+=("$cmd")
    fi
done

if (( ${#missing[@]} > 0 )); then
    echo "ERROR: missing required commands: ${missing[*]}" >&2
    echo "       install with: apt install ${missing[*]}" >&2
    exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
    echo "ERROR: 'docker compose' plugin not available" >&2
    echo "       install with: apt install docker-compose-plugin" >&2
    exit 1
fi

if [[ ! -f "$LLM_SCRIPT" ]]; then
    echo "ERROR: $LLM_SCRIPT not found" >&2
    echo "       make sure you have the companion script installed first" >&2
    exit 1
fi

echo "    OK — jq, docker, docker compose, llm-switch.sh all present"

# --- Directories ------------------------------------------------------------

echo "==> [2/6] Creating directories..."
mkdir -p "$REQUESTS_DIR" "$RESPONSES_DIR"

# Requests: sticky bit + world-writable, so any container user can drop a
# request. This is safe because llm-switch.sh enforces the profile whitelist —
# directory permissions are not the security boundary.
chmod 1777 "$REQUESTS_DIR"

# Responses: world-readable so any client can poll.
chmod 0755 "$RESPONSES_DIR"
chmod 0755 "$SWITCH_DIR"

echo "    created:"
echo "      $REQUESTS_DIR   (1777)"
echo "      $RESPONSES_DIR  (0755)"

# --- Script permissions -----------------------------------------------------

echo "==> [3/6] Making llm-switch.sh executable..."
chmod 0755 "$LLM_SCRIPT"
echo "    OK"

# --- Systemd path unit ------------------------------------------------------

echo "==> [4/6] Writing $PATH_UNIT..."
cat > "$PATH_UNIT" <<'EOF'
[Unit]
Description=Watch for Mora02 LLM profile switch requests
After=docker.service

[Path]
DirectoryNotEmpty=/opt/mora02/llm-switch/requests

[Install]
WantedBy=multi-user.target
EOF
echo "    written"

# --- Systemd service unit ---------------------------------------------------

echo "==> [5/6] Writing $SERVICE_UNIT..."
cat > "$SERVICE_UNIT" <<'EOF'
[Unit]
Description=Mora02 LLM profile switch executor
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
Environment="PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ExecStart=/opt/mora02/scripts/llm-switch.sh
User=root
StandardOutput=journal
StandardError=journal
EOF
echo "    written"

# --- Activate ---------------------------------------------------------------

echo "==> [6/6] Activating systemd units..."
systemctl daemon-reload
systemctl enable llm-switch.path
systemctl restart llm-switch.path

echo "    enabled & started llm-switch.path"
echo

# --- Verification -----------------------------------------------------------

echo "==> Verification:"
systemctl --no-pager status llm-switch.path || true
echo

# --- Summary ----------------------------------------------------------------

cat <<EOF

==============================================================================
 Installation complete!
==============================================================================

 Briefkasten:
   Requests:  $REQUESTS_DIR/
   Responses: $RESPONSES_DIR/

 Manual test (run as root):
   echo '{"request_id":"test-1","profile":"qwen3-14b"}' > $REQUESTS_DIR/test-1.json
   sleep 3
   cat $RESPONSES_DIR/test-1.json

 Watch live logs:
   journalctl -u llm-switch.service -f

 Disable (if needed):
   systemctl disable --now llm-switch.path

==============================================================================
EOF
