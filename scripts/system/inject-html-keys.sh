#!/bin/bash
# Ersetzt %%PLACEHOLDER%% in HTML-Dateien mit Werten aus .env
# Wird beim Systemstart oder nach .env-Änderungen ausgeführt

set -euo pipefail
BASE="/opt/mora02"
source "$BASE/docker/.env"

replace_placeholder() {
    local file="$1"
    local placeholder="$2"
    local value="$3"
    
    if [ -f "$file" ] && grep -q "$placeholder" "$file" 2>/dev/null; then
        sed -i "s|${placeholder}|${value}|g" "$file"
        echo "  ✓ $(basename $file): $placeholder"
    fi
}

echo "Injecting HTML keys from .env..."

replace_placeholder "$BASE/docs/assistant/index.html" \
    "%%DIFY_APP_KEY_ASSISTANT%%" "${DIFY_APP_KEY_ASSISTANT:-}"

replace_placeholder "$BASE/docs/daily_bot/html/index.html" \
    "%%DIFY_APP_KEY_DAILY%%" "${DIFY_APP_KEY_DAILY:-}"

replace_placeholder "$BASE/apps/_archive/socialmedia-bot/index.html" \
    "%%DIFY_APP_KEY_SOCIALMEDIA%%" "${DIFY_APP_KEY_SOCIALMEDIA:-}"

echo "Done."
