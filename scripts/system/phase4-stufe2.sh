#!/bin/bash
# ============================================================
# Mora02 Phase 4 — Stufe 2: Docker Umschalten
# ============================================================
# Benennt Ordner um und aktualisiert alle Referenzen:
# - docker-compose.yml (Volume Mounts)
# - nginx-images/nginx.conf
# - knowledge-api.py (interne Pfade)
# - script-runner main.py
# - crontab
#
# VORAUSSETZUNG: Stufe 1 erfolgreich, Borg Backup aktuell
# ============================================================

set -euo pipefail

BASE="/opt/mora02"
COMPOSE="$BASE/docker/docker-compose.yml"
NGINX_CONF="$BASE/docker/nginx-images/nginx.conf"
LOG="$BASE/backups/phase4-stufe2-$(date +%Y%m%d%H%M).log"
DRY_RUN="${1:-}"
ERRORS=0

log() { echo "[$(date +%H:%M:%S)] $1" | tee -a "$LOG"; }
err() { echo "[$(date +%H:%M:%S)] ❌ $1" | tee -a "$LOG"; ERRORS=$((ERRORS+1)); }
run() {
    if [ "$DRY_RUN" = "--dry-run" ]; then
        echo "[DRY-RUN] $1" | tee -a "$LOG"
    else
        eval "$1" 2>&1 | tee -a "$LOG" || err "Fehlgeschlagen: $1"
    fi
}

echo "============================================================"
echo "  Mora02 Phase 4 — Stufe 2: Docker Umschalten"
echo "  $(date)"
[ "$DRY_RUN" = "--dry-run" ] && echo "  *** DRY-RUN MODUS ***"
echo "============================================================"

# === SAFETY CHECKS ===
if [ ! -d "$BASE/apps/pilot" ]; then
    echo "FEHLER: apps/pilot/ nicht gefunden. Stufe 1 zuerst ausführen!"
    exit 1
fi

if [ ! -d "$BASE/output/_default" ]; then
    echo "FEHLER: output/_default/ nicht gefunden. Stufe 1 zuerst ausführen!"
    exit 1
fi

# ============================================================
# SCHRITT 0: Backups
# ============================================================
log "=== SCHRITT 0: Sicherungskopien ==="

run "cp '$COMPOSE' '$BASE/backups/docker-compose-pre-phase4.yml'"
run "cp '$NGINX_CONF' '$BASE/backups/nginx-conf-pre-phase4.conf'"
log "✓ Backup erstellt"

# ============================================================
# SCHRITT 1: Docker stoppen
# ============================================================
log "=== SCHRITT 1: Docker stoppen ==="

if [ "$DRY_RUN" != "--dry-run" ]; then
    cd "$BASE/docker"
    docker compose down 2>&1 | tee -a "$LOG"
    log "✓ Docker gestoppt"
else
    log "[DRY-RUN] docker compose down"
fi

# ============================================================
# SCHRITT 2: Ordner umbenennen
# ============================================================
log "=== SCHRITT 2: Ordner umbenennen ==="

# data/ → volumes/
if [ -d "$BASE/data" ] && [ ! -d "$BASE/volumes" ]; then
    run "mv '$BASE/data' '$BASE/volumes'"
    log "  ✓ data/ → volumes/"
else
    log "  ⚠ data/ → volumes/ übersprungen (existiert bereits oder fehlt)"
fi

# ai_models/ → ai-models/
if [ -d "$BASE/ai_models" ] && [ ! -d "$BASE/ai-models" ]; then
    run "mv '$BASE/ai_models' '$BASE/ai-models'"
    log "  ✓ ai_models/ → ai-models/"
fi

# ai-models/llama_cpp/ → ai-models/llama-cpp/
if [ -d "$BASE/ai-models/llama_cpp" ] && [ ! -d "$BASE/ai-models/llama-cpp" ]; then
    run "mv '$BASE/ai-models/llama_cpp' '$BASE/ai-models/llama-cpp'"
    log "  ✓ llama_cpp/ → llama-cpp/"
fi

# docker/open_web_ui/ → docker/open-webui/
if [ -d "$BASE/docker/open_web_ui" ] && [ ! -d "$BASE/docker/open-webui" ]; then
    run "mv '$BASE/docker/open_web_ui' '$BASE/docker/open-webui'"
    log "  ✓ open_web_ui/ → open-webui/"
fi

# Alte Leichen löschen
run "rm -rf '$BASE/docker/_old_docker-compose' 2>/dev/null || true"
run "rm -rf '$BASE/docs/comfyui/image' 2>/dev/null || true"
run "rm -rf '$BASE/docs/nginx-assets' 2>/dev/null || true"
run "rm -rf '$BASE/docs/socialmedia/drafts' 2>/dev/null || true"
run "rm -rf '$BASE/docs/socialmedia/published' 2>/dev/null || true"
run "rm -rf '$BASE/docs/socialmedia/strategy' 2>/dev/null || true"
run "rm -f  '$BASE/docs/socialmedia/LINKEDIN KEYS.txt' 2>/dev/null || true"
run "rm -f  '$BASE/config/baserow-token.txt' 2>/dev/null || true"
run "rm -rf '$BASE/logs' 2>/dev/null || true"
log "  ✓ Leichen entfernt"

# ============================================================
# SCHRITT 3: docker-compose.yml Mount-Pfade updaten
# ============================================================
log "=== SCHRITT 3: docker-compose.yml updaten ==="

if [ "$DRY_RUN" != "--dry-run" ]; then

    # --- data/ → volumes/ ---
    sed -i 's|/opt/mora02/data/|/opt/mora02/volumes/|g' "$COMPOSE"
    # The comfyui data mount (standalone /data not /data/)
    sed -i 's|- /opt/mora02/data:|- /opt/mora02/volumes:|g' "$COMPOSE"
    log "  ✓ data → volumes"

    # --- ai_models/ → ai-models/ ---
    sed -i 's|/opt/mora02/ai_models/|/opt/mora02/ai-models/|g' "$COMPOSE"
    log "  ✓ ai_models → ai-models"

    # --- ai-models/llama_cpp → ai-models/llama-cpp ---
    sed -i 's|/ai-models/llama_cpp/|/ai-models/llama-cpp/|g' "$COMPOSE"
    log "  ✓ llama_cpp → llama-cpp"

    # --- open_web_ui → open-webui ---
    sed -i 's|/docker/open_web_ui|/docker/open-webui|g' "$COMPOSE"
    log "  ✓ open_web_ui → open-webui"

    # --- docs/ → apps/ (Frontends) ---
    sed -i 's|/opt/mora02/docs/pilot/html|/opt/mora02/apps/pilot/frontend|g' "$COMPOSE"
    sed -i 's|/opt/mora02/docs/script-bot/html|/opt/mora02/apps/script-runner/frontend|g' "$COMPOSE"
    sed -i 's|/opt/mora02/docs/assistant|/opt/mora02/apps/_archive/assistant|g' "$COMPOSE"
    sed -i 's|/opt/mora02/docs/daily_bot/html|/opt/mora02/apps/_archive/daily-bot|g' "$COMPOSE"
    sed -i 's|/opt/mora02/docs/socialmedia/socialmedia-bot|/opt/mora02/apps/_archive/socialmedia-bot|g' "$COMPOSE"
    log "  ✓ Frontends → apps/"

    # --- docs/ → output/ (Assets) ---
    sed -i 's|/opt/mora02/docs/comfyui/images/wip|/opt/mora02/output/_default/comfyui/wip|g' "$COMPOSE"
    sed -i 's|/opt/mora02/docs/comfyui/images|/opt/mora02/output/_default/comfyui|g' "$COMPOSE"
    sed -i 's|/opt/mora02/docs/socialmedia/assets|/opt/mora02/output/_default/socialmedia|g' "$COMPOSE"
    sed -i 's|/opt/mora02/docs/script-bot/final|/opt/mora02/output/_default/script-bot/final|g' "$COMPOSE"
    sed -i 's|/opt/mora02/docs/script-bot|/opt/mora02/output/_default/script-bot|g' "$COMPOSE"
    log "  ✓ Assets → output/"

    # --- Activepieces: docs → output (broad mount) ---
    # AP hatte /opt/mora02/docs gemountet — jetzt braucht es output/ statt docs/
    sed -i 's|- /opt/mora02/docs:/opt/mora02/docs|- /opt/mora02/output:/opt/mora02/output|g' "$COMPOSE"
    log "  ✓ Activepieces Mount: docs → output"

    # Verify
    REMAINING=$(grep -c "/opt/mora02/docs/" "$COMPOSE" 2>/dev/null || echo "0")
    if [ "$REMAINING" -gt 0 ]; then
        err "Noch $REMAINING Referenzen auf /opt/mora02/docs/ in docker-compose.yml!"
        grep -n "/opt/mora02/docs/" "$COMPOSE" | tee -a "$LOG"
    else
        log "  ✓ Keine docs/-Referenzen mehr in compose"
    fi

    REMAINING_DATA=$(grep -c "/opt/mora02/data" "$COMPOSE" 2>/dev/null || echo "0")
    if [ "$REMAINING_DATA" -gt 0 ]; then
        err "Noch $REMAINING_DATA Referenzen auf /opt/mora02/data in docker-compose.yml!"
        grep -n "/opt/mora02/data" "$COMPOSE" | tee -a "$LOG"
    else
        log "  ✓ Keine data/-Referenzen mehr in compose"
    fi

else
    log "[DRY-RUN] sed-Befehle auf docker-compose.yml"
fi

# ============================================================
# SCHRITT 4: nginx.conf updaten
# ============================================================
log "=== SCHRITT 4: nginx.conf updaten ==="

if [ "$DRY_RUN" != "--dry-run" ]; then
    # Die alias-Direktiven zeigen auf Container-interne Pfade
    # Die Mounts in compose wurden schon geändert — nginx sieht die neuen Pfade automatisch
    # ABER: Falls nginx.conf Host-Pfade referenziert, müssen die auch angepasst werden
    # nginx-images mountet Ordner nach /usr/share/nginx/html/* — diese Container-Pfade ändern sich NICHT
    log "  ✓ nginx.conf — keine Änderung nötig (Container-interne Pfade bleiben gleich)"
fi

# ============================================================
# SCHRITT 5: Code-Dateien anpassen
# ============================================================
log "=== SCHRITT 5: Code-Dateien anpassen ==="

# knowledge-api.py (in der neuen apps/ Kopie UND im alten docker/)
for KA in "$BASE/apps/knowledge-api/backend/knowledge-api.py" \
          "$BASE/docker/knowledge-api/knowledge-api.py"; do
    if [ -f "$KA" ] && [ "$DRY_RUN" != "--dry-run" ]; then
        sed -i 's|/opt/mora02/data/knowledge-sync-status.txt|/opt/mora02/volumes/knowledge-sync-status.txt|g' "$KA"
        sed -i 's|/opt/mora02/data/knowledge-base|/opt/mora02/volumes/knowledge-base|g' "$KA"
        sed -i 's|docs_dir = "/opt/mora02/docs/system"|docs_dir = "/opt/mora02/knowledge/handbook"|g' "$KA"
        # Scripts Pfade
        sed -i 's|/opt/mora02/scripts/update-knowledge-base.sh|/opt/mora02/scripts/system/update-knowledge-base.sh|g' "$KA"
        sed -i 's|/opt/mora02/scripts/generate-session-summary.py|/opt/mora02/scripts/system/generate-session-summary.py|g' "$KA"
        sed -i 's|/opt/mora02/scripts/export-sessions-to-knowledge.py|/opt/mora02/scripts/system/export-sessions-to-knowledge.py|g' "$KA"
        log "  ✓ $(basename $(dirname $KA))/knowledge-api.py"
    fi
done

# script-runner main.py
for SR in "$BASE/apps/script-runner/backend/app/main.py" \
          "$BASE/docker/script-runner/app/main.py"; do
    if [ -f "$SR" ] && [ "$DRY_RUN" != "--dry-run" ]; then
        sed -i 's|HOST_DATA_PATH = "/opt/mora02/docs/script-bot"|HOST_DATA_PATH = "/opt/mora02/output/_default/script-bot"|g' "$SR"
        log "  ✓ $(basename $(dirname $(dirname $SR)))/main.py"
    fi
done

# ============================================================
# SCHRITT 6: Crontab aktualisieren
# ============================================================
log "=== SCHRITT 6: Crontab aktualisieren ==="

if [ "$DRY_RUN" != "--dry-run" ]; then
    # Export current crontab
    crontab -l > /tmp/mora02-crontab-backup.txt 2>/dev/null || true
    run "cp /tmp/mora02-crontab-backup.txt '$BASE/backups/crontab-pre-phase4.txt'"

    # Create new crontab
    crontab -l 2>/dev/null | \
        sed 's|/opt/mora02/scripts/archive.sh /opt/mora02/docs/pexels|/opt/mora02/scripts/system/archive.sh /opt/mora02/output/_default/pexels|g' | \
        sed 's|/opt/mora02/scripts/archive.sh /opt/mora02/docs/gifer|/opt/mora02/scripts/system/archive.sh /opt/mora02/output/_default/gifer|g' | \
        sed 's|/opt/mora02/scripts/archive.sh /opt/mora02/docs/pixabay|/opt/mora02/scripts/system/archive.sh /opt/mora02/output/_default/pixabay|g' | \
        sed 's|/opt/mora02/logs/archive.log|/opt/mora02/knowledge/archive/archive.log|g' | \
        sed 's|/opt/mora02/scripts/update-knowledge-base.sh|/opt/mora02/scripts/system/update-knowledge-base.sh|g' | \
        sed 's|/opt/mora02/data/knowledge-base/cron.log|/opt/mora02/volumes/knowledge-base/cron.log|g' | \
        crontab -
    log "  ✓ Crontab aktualisiert"
else
    log "[DRY-RUN] Crontab würde aktualisiert"
fi

# ============================================================
# SCHRITT 7: Compose Syntax-Check
# ============================================================
log "=== SCHRITT 7: Compose Syntax-Check ==="

if [ "$DRY_RUN" != "--dry-run" ]; then
    cd "$BASE/docker"
    if docker compose config --quiet 2>&1 | tee -a "$LOG"; then
        log "✓ Compose Syntax OK"
    else
        err "Compose Syntax-Fehler! Rollback empfohlen."
        echo ""
        echo "ROLLBACK-BEFEHLE:"
        echo "  cp $BASE/backups/docker-compose-pre-phase4.yml $COMPOSE"
        echo "  mv $BASE/volumes $BASE/data"
        echo "  mv $BASE/ai-models $BASE/ai_models"
        echo "  mv $BASE/ai_models/llama-cpp $BASE/ai_models/llama_cpp"
        echo "  cat $BASE/backups/crontab-pre-phase4.txt | crontab -"
        exit 1
    fi
fi

# ============================================================
# SCHRITT 8: Docker starten
# ============================================================
log "=== SCHRITT 8: Docker starten ==="

if [ "$DRY_RUN" != "--dry-run" ]; then
    cd "$BASE/docker"
    docker compose up -d 2>&1 | tee -a "$LOG"
    log "✓ Docker gestartet"
    sleep 15
fi

# ============================================================
# SCHRITT 9: Health Checks
# ============================================================
log "=== SCHRITT 9: Health Checks ==="

check_service() {
    local NAME="$1"
    local URL="$2"
    local EXPECT="$3"

    if [ "$DRY_RUN" = "--dry-run" ]; then
        log "  [DRY-RUN] $NAME → $URL"
        return
    fi

    RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$URL" 2>/dev/null || echo "000")
    if [ "$RESPONSE" = "$EXPECT" ]; then
        log "  ✅ $NAME ($RESPONSE)"
    else
        err "$NAME: erwartet $EXPECT, bekommen $RESPONSE"
    fi
}

check_service "Baserow" "http://localhost:8085/api/settings/" "200"
check_service "Dify Web" "http://localhost:8190" "200"
check_service "Dify API" "http://localhost:8191/v1/models" "200"
check_service "Activepieces" "http://localhost:8089" "200"
check_service "nginx-images" "http://localhost:8092" "200"
check_service "Knowledge API" "http://localhost:8095/health" "200"
check_service "Script Runner" "http://localhost:8096/health" "200"
check_service "Pilot" "http://localhost:8098" "200"
check_service "Penpot" "http://localhost:8101" "200"
check_service "Excalidraw" "http://localhost:8102" "200"
check_service "SearXNG" "http://localhost:8094" "200"
check_service "Open WebUI" "http://localhost:3000" "200"
check_service "LLM (Qwen)" "http://localhost:8080/health" "200"
check_service "ComfyUI" "http://localhost:8188" "200"

# Docker container status
if [ "$DRY_RUN" != "--dry-run" ]; then
    echo "" | tee -a "$LOG"
    log "Container Status:"
    docker ps --format "  {{.Names}}: {{.Status}}" 2>&1 | tee -a "$LOG"
    STOPPED=$(docker ps -a --filter "status=exited" --format "{{.Names}}" 2>/dev/null)
    if [ -n "$STOPPED" ]; then
        err "Gestoppte Container: $STOPPED"
    fi
fi

# ============================================================
# REPORT
# ============================================================
echo ""
echo "============================================================"
echo "  Stufe 2 FERTIG"
echo "============================================================"
echo ""
echo "  Fehler: $ERRORS"
echo "  Log: $LOG"
echo ""
if [ "$ERRORS" -gt 0 ]; then
    echo "  ⚠ Es gab Fehler! Bitte Log prüfen."
    echo ""
    echo "  ROLLBACK falls nötig:"
    echo "    cp $BASE/backups/docker-compose-pre-phase4.yml $COMPOSE"
    echo "    mv $BASE/volumes $BASE/data"
    echo "    mv $BASE/ai-models $BASE/ai_models"
    echo "    mv $BASE/ai_models/llama-cpp $BASE/ai_models/llama_cpp"
    echo "    mv $BASE/docker/open-webui $BASE/docker/open_web_ui"
    echo "    cat $BASE/backups/crontab-pre-phase4.txt | crontab -"
    echo "    cd $BASE/docker && docker compose up -d"
else
    echo "  ✅ Alles OK!"
    echo ""
    echo "  NÄCHSTE SCHRITTE:"
    echo "    1. Stichproben: Pilot im Browser öffnen, Bild generieren, Flow testen"
    echo "    2. Activepieces: ~10 Flows mit alten Pfaden manuell anpassen"
    echo "    3. xray-Scan: python3 /opt/mora02/scripts/xray/mora02-xray.py"
    echo "    4. Alte docs/ Unterordner aufräumen (die jetzt woanders liegen)"
fi
echo "============================================================"
