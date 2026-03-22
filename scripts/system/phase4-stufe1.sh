#!/bin/bash
# ============================================================
# Mora02 Phase 4 — Stufe 1: Kopieren & Sortieren
# ============================================================
# Erstellt neue Struktur PARALLEL zur alten.
# Nichts wird gelöscht oder verschoben. Nur kopiert.
# Sicher abzubrechen an jedem Punkt.
#
# Voraussetzung: Borg Backup wurde erstellt
# ============================================================

set -euo pipefail

BASE="/opt/mora02"
LOG="$BASE/backups/phase4-stufe1-$(date +%Y%m%d%H%M).log"
DRY_RUN="${1:-}"

log() { echo "[$(date +%H:%M:%S)] $1" | tee -a "$LOG"; }
run() {
    if [ "$DRY_RUN" = "--dry-run" ]; then
        echo "[DRY-RUN] $1" | tee -a "$LOG"
    else
        eval "$1" 2>&1 | tee -a "$LOG"
    fi
}

echo "============================================================"
echo "  Mora02 Phase 4 — Stufe 1: Kopieren & Sortieren"
echo "  $(date)"
[ "$DRY_RUN" = "--dry-run" ] && echo "  *** DRY-RUN MODUS ***"
echo "============================================================"

# === SAFETY CHECKS ===
if [ ! -f "$BASE/docker/docker-compose.yml" ]; then
    echo "FEHLER: docker-compose.yml nicht gefunden. Falscher Pfad?"
    exit 1
fi

if [ -d "$BASE/apps" ] && [ "$(ls -A $BASE/apps 2>/dev/null)" ]; then
    echo "WARNUNG: $BASE/apps/ existiert bereits und ist nicht leer."
    echo "Wurde Stufe 1 schon ausgeführt? Abbruch."
    exit 1
fi

# ============================================================
# TEIL 1: Neue Top-Level Ordner erstellen
# ============================================================
log "=== TEIL 1: Ordnerstruktur erstellen ==="

for dir in \
    apps/pilot/backend \
    apps/pilot/frontend \
    apps/script-runner/backend \
    apps/knowledge-api/backend \
    apps/_archive/assistant \
    apps/_archive/daily-bot \
    apps/_archive/socialmedia-bot \
    scripts/gifer \
    scripts/pexels \
    scripts/pixabay \
    scripts/clipper \
    scripts/typer \
    scripts/xray \
    scripts/backup \
    scripts/docker \
    scripts/system \
    scripts/changelog \
    scripts/_archive \
    output/_default/comfyui/wip \
    output/_default/comfyui/final \
    output/_default/gifer \
    output/_default/pexels \
    output/_default/pixabay \
    output/_default/clipper \
    output/_default/typer \
    output/_default/socialmedia \
    output/_default/dify-assets/wip \
    output/_default/dify-assets/final \
    output/_default/script-bot/wip \
    output/_default/script-bot/final \
    knowledge/handbook \
    knowledge/changelog \
    knowledge/sessions \
    knowledge/benchmarks \
    knowledge/x-ray \
    knowledge/archive \
    knowledge/archive/tests \
    knowledge/archive/dify-copy-writer \
    knowledge/archive/dify-general-chat \
    knowledge/archive/dify-system-assistant \
    config/vpn \
; do
    run "mkdir -p $BASE/$dir"
done
log "✓ Ordnerstruktur erstellt"

# ============================================================
# TEIL 2: Apps kopieren
# ============================================================
log "=== TEIL 2: Apps kopieren ==="

# Pilot Backend
if [ -d "$BASE/docker/pilot" ]; then
    run "cp -a $BASE/docker/pilot/* $BASE/apps/pilot/backend/ 2>/dev/null || true"
    log "  ✓ pilot/backend"
fi

# Pilot Frontend
if [ -d "$BASE/docs/pilot/html" ]; then
    run "cp -a $BASE/docs/pilot/html/* $BASE/apps/pilot/frontend/"
    log "  ✓ pilot/frontend"
fi

# Script-Runner Backend
if [ -d "$BASE/docker/script-runner" ]; then
    run "cp -a $BASE/docker/script-runner/* $BASE/apps/script-runner/backend/ 2>/dev/null || true"
    log "  ✓ script-runner/backend"
fi

# Script-Runner Frontend (script-bot HTML)
if [ -d "$BASE/docs/script-bot/html" ]; then
    run "mkdir -p $BASE/apps/script-runner/frontend"
    run "cp -a $BASE/docs/script-bot/html/* $BASE/apps/script-runner/frontend/"
    log "  ✓ script-runner/frontend"
fi

# Knowledge-API Backend
if [ -d "$BASE/docker/knowledge-api" ]; then
    run "cp -a $BASE/docker/knowledge-api/* $BASE/apps/knowledge-api/backend/ 2>/dev/null || true"
    log "  ✓ knowledge-api/backend"
fi

# Archive: Alte Bots
if [ -d "$BASE/docs/assistant" ]; then
    run "cp -a $BASE/docs/assistant/* $BASE/apps/_archive/assistant/"
    log "  ✓ _archive/assistant"
fi
if [ -d "$BASE/docs/daily_bot/html" ]; then
    run "cp -a $BASE/docs/daily_bot/html/* $BASE/apps/_archive/daily-bot/"
    log "  ✓ _archive/daily-bot"
fi
if [ -d "$BASE/docs/socialmedia/socialmedia-bot" ]; then
    run "cp -a $BASE/docs/socialmedia/socialmedia-bot/* $BASE/apps/_archive/socialmedia-bot/"
    log "  ✓ _archive/socialmedia-bot"
fi

# ============================================================
# TEIL 3: Output kopieren (NUR Inhalte, nicht Ordner-Struktur)
# ============================================================
log "=== TEIL 3: Output kopieren ==="

# ComfyUI Images
if [ -d "$BASE/docs/comfyui/images/wip" ]; then
    run "cp -a $BASE/docs/comfyui/images/wip/* $BASE/output/_default/comfyui/wip/ 2>/dev/null || true"
    log "  ✓ comfyui/wip"
fi
if [ -d "$BASE/docs/comfyui/images/final" ]; then
    run "cp -a $BASE/docs/comfyui/images/final/* $BASE/output/_default/comfyui/final/ 2>/dev/null || true"
    log "  ✓ comfyui/final"
fi

# Tool Outputs
for tool in gifer pexels pixabay clipper typer; do
    if [ -d "$BASE/docs/$tool" ]; then
        run "cp -a $BASE/docs/$tool/* $BASE/output/_default/$tool/ 2>/dev/null || true"
        log "  ✓ $tool"
    fi
done

# Socialmedia Assets
if [ -d "$BASE/docs/socialmedia/assets" ]; then
    run "cp -a $BASE/docs/socialmedia/assets/* $BASE/output/_default/socialmedia/ 2>/dev/null || true"
    log "  ✓ socialmedia"
fi

# Dify Assets
if [ -d "$BASE/docs/dify/assets/wip" ]; then
    run "cp -a $BASE/docs/dify/assets/wip/* $BASE/output/_default/dify-assets/wip/ 2>/dev/null || true"
    log "  ✓ dify-assets/wip"
fi
if [ -d "$BASE/docs/dify/assets/final" ]; then
    run "cp -a $BASE/docs/dify/assets/final/* $BASE/output/_default/dify-assets/final/ 2>/dev/null || true"
    log "  ✓ dify-assets/final"
fi

# Script-Bot WIP/Final
if [ -d "$BASE/docs/script-bot/wip" ]; then
    run "cp -a $BASE/docs/script-bot/wip/* $BASE/output/_default/script-bot/wip/ 2>/dev/null || true"
    log "  ✓ script-bot/wip"
fi
if [ -d "$BASE/docs/script-bot/final" ]; then
    run "cp -a $BASE/docs/script-bot/final/* $BASE/output/_default/script-bot/final/ 2>/dev/null || true"
    log "  ✓ script-bot/final"
fi
# Also scripts/wip and scripts/final (same content structure)
if [ -d "$BASE/docs/scripts/wip" ]; then
    run "cp -a $BASE/docs/scripts/wip/* $BASE/output/_default/script-bot/wip/ 2>/dev/null || true"
    log "  ✓ scripts/wip → script-bot/wip"
fi
if [ -d "$BASE/docs/scripts/final" ]; then
    run "cp -a $BASE/docs/scripts/final/* $BASE/output/_default/script-bot/final/ 2>/dev/null || true"
    log "  ✓ scripts/final → script-bot/final"
fi

# ============================================================
# TEIL 4: Knowledge kopieren
# ============================================================
log "=== TEIL 4: Knowledge kopieren ==="

# Handbook: Betriebshandbuch (neueste Version)
NEWEST_HB=$(ls -t $BASE/docs/system/*betriebshandbuch* 2>/dev/null | head -1)
if [ -n "$NEWEST_HB" ]; then
    run "cp '$NEWEST_HB' $BASE/knowledge/handbook/betriebshandbuch.md"
    log "  ✓ betriebshandbuch ($(basename $NEWEST_HB))"
fi

# Handbook: Nomenklatur
NOMENKLATUR=$(ls -t $BASE/docs/system/*nomenklatur* 2>/dev/null | head -1)
if [ -n "$NOMENKLATUR" ]; then
    run "cp '$NOMENKLATUR' $BASE/knowledge/handbook/nomenklatur.md"
    log "  ✓ nomenklatur"
fi

# Handbook: Referenzen
for ref in baserow-api-reference activepieces-workflow-guide dify-tool-specs; do
    FILE=$(ls -t $BASE/docs/system/*${ref}* 2>/dev/null | head -1)
    if [ -n "$FILE" ]; then
        run "cp '$FILE' '$BASE/knowledge/handbook/$(basename $FILE)'"
        log "  ✓ $ref"
    fi
done

# Changelog (ganzer Ordner)
if [ -d "$BASE/docs/changelog" ]; then
    run "cp -a $BASE/docs/changelog/* $BASE/knowledge/changelog/"
    log "  ✓ changelog ($(du -sh $BASE/docs/changelog | cut -f1))"
fi

# Sessions
if [ -d "$BASE/docs/sessions" ]; then
    run "cp -a $BASE/docs/sessions/* $BASE/knowledge/sessions/ 2>/dev/null || true"
    log "  ✓ sessions"
fi

# Benchmarks
if [ -d "$BASE/docs/benchmarks" ]; then
    run "cp -a $BASE/docs/benchmarks/* $BASE/knowledge/benchmarks/"
    log "  ✓ benchmarks"
fi

# X-Ray Reports
if [ -d "$BASE/docs/system/x-ray" ]; then
    run "cp -a $BASE/docs/system/x-ray/* $BASE/knowledge/x-ray/"
    log "  ✓ x-ray"
fi

# Archive: alte APs, Roadmaps, Konzepte (alles aus system/ was nicht Handbook ist)
log "  Archiviere docs/system/ Restdateien..."
for f in "$BASE"/docs/system/*.md "$BASE"/docs/system/*.txt; do
    [ -f "$f" ] || continue
    BN=$(basename "$f")
    # Skip: bereits nach handbook kopiert
    case "$BN" in
        *betriebshandbuch*|*nomenklatur*|*baserow-api-reference*|*activepieces-workflow-guide*|*dify-tool-specs*)
            continue ;;
    esac
    run "cp '$f' '$BASE/knowledge/archive/$BN'"
done
log "  ✓ archive (docs/system Rest)"

# Archive: Tests
if [ -d "$BASE/docs/tests" ]; then
    run "cp -a $BASE/docs/tests/* $BASE/knowledge/archive/tests/"
    log "  ✓ archive/tests"
fi

# Archive: Alte Dify Bot Outputs
for bot in copy-writer general-chat system-assistant; do
    if [ -d "$BASE/docs/dify/$bot" ]; then
        run "cp -a $BASE/docs/dify/$bot/* $BASE/knowledge/archive/dify-$bot/ 2>/dev/null || true"
        log "  ✓ archive/dify-$bot"
    fi
done

# ============================================================
# TEIL 5: Scripts reorganisieren
# ============================================================
log "=== TEIL 5: Scripts reorganisieren ==="

# Gifer (aktive Version)
[ -f "$BASE/scripts/202512101632_gifer.py" ] && \
    run "cp $BASE/scripts/202512101632_gifer.py $BASE/scripts/gifer/gifer.py"

# Pexels (aktive Version = pexels_multi)
[ -f "$BASE/scripts/202512101825_pexels_multi.py" ] && \
    run "cp $BASE/scripts/202512101825_pexels_multi.py $BASE/scripts/pexels/pexels.py"

# Pixabay
[ -f "$BASE/scripts/202512101747_pixabay.py" ] && \
    run "cp $BASE/scripts/202512101747_pixabay.py $BASE/scripts/pixabay/pixabay.py"

# Clipper (suche aktive Version)
CLIPPER=$(ls -t $BASE/scripts/*clipper* 2>/dev/null | head -1)
[ -n "$CLIPPER" ] && run "cp '$CLIPPER' $BASE/scripts/clipper/clipper.py"

# Typer (suche aktive Version)
TYPER=$(ls -t $BASE/scripts/*typer* 2>/dev/null | head -1)
[ -n "$TYPER" ] && run "cp '$TYPER' $BASE/scripts/typer/typer.py"

# xray
[ -f "$BASE/scripts/mora02-xray.py" ] && \
    run "cp $BASE/scripts/mora02-xray.py $BASE/scripts/xray/mora02-xray.py"

# Backup scripts
for f in backup_run.sh backup_list.sh borg-prune-dryrun.sh borg-prune-live.sh; do
    KEBAB=$(echo "$f" | sed 's/_/-/g')
    [ -f "$BASE/scripts/$f" ] && run "cp $BASE/scripts/$f $BASE/scripts/backup/$KEBAB"
done

# Docker scripts
for f in docker-up.sh docker-down.sh docker_restart.sh docker_status.sh; do
    KEBAB=$(echo "$f" | sed 's/_/-/g')
    [ -f "$BASE/scripts/$f" ] && run "cp $BASE/scripts/$f $BASE/scripts/docker/$KEBAB"
done

# System scripts
for f in gpu-monitor.sh hardware-info.sh directory-info.sh directory-snapshot.sh \
         archive.sh inject-html-keys.sh gnome_custom_shortcuts.sh gnome_shortcuts_open.sh \
         setup.sh test_gpu.sh snapshot-system-state.sh update-knowledge-base.sh \
         generate-session-summary.py export-sessions-to-knowledge.py; do
    KEBAB=$(echo "$f" | sed 's/_/-/g')
    [ -f "$BASE/scripts/$f" ] && run "cp '$BASE/scripts/$f' '$BASE/scripts/system/$KEBAB'"
done

# Changelog script
[ -f "$BASE/scripts/build-changelog.py" ] && \
    run "cp $BASE/scripts/build-changelog.py $BASE/scripts/changelog/build-changelog.py"
# Alternative name
[ -f "$BASE/scripts/mora02-changelog-builder.py" ] && \
    run "cp $BASE/scripts/mora02-changelog-builder.py $BASE/scripts/changelog/build-changelog.py"

# Archive: Alte/Test Scripts
for f in "$BASE"/scripts/202512101710_pexels.py \
         "$BASE"/scripts/202512101810_pexels_fixed.py \
         "$BASE"/scripts/202512101823_image-to-gif.py \
         "$BASE"/scripts/2602081400_daily-bot-test.py \
         "$BASE"/scripts/2602081930_daily-bot-test-v4.py \
         "$BASE"/scripts/2602082100_daily-bot-test-v4.1.py \
         "$BASE"/scripts/index-mora02-docs.py \
         "$BASE"/scripts/openwebui-function-handler.py \
         "$BASE"/scripts/ollama-web-search-hook.py \
         "$BASE"/scripts/searxng-wrapper.py \
         "$BASE"/scripts/mora02_rag_*.py \
         "$BASE"/scripts/mora_file_agent.py; do
    [ -f "$f" ] && run "cp '$f' '$BASE/scripts/_archive/'"
done
# Index scripts
for f in "$BASE"/scripts/index-system-snapshot*.py; do
    [ -f "$f" ] && run "cp '$f' '$BASE/scripts/_archive/'"
done
log "  ✓ Scripts reorganisiert"

# ============================================================
# TEIL 6: Config / VPN
# ============================================================
log "=== TEIL 6: Config ==="

if [ -d "$BASE/docs/VPN_guests" ]; then
    run "cp -a $BASE/docs/VPN_guests/* $BASE/config/vpn/"
    log "  ✓ VPN Configs"
fi
if [ -f "$BASE/docs/system/2512022203_VPN_keys.txt" ]; then
    run "cp $BASE/docs/system/2512022203_VPN_keys.txt $BASE/config/vpn/vpn-keys.txt"
    log "  ✓ VPN Keys"
fi

# ============================================================
# TEIL 7: READMEs generieren
# ============================================================
log "=== TEIL 7: READMEs generieren ==="

generate_readme() {
    local DIR="$1"
    local TITLE="$2"
    local DESC="$3"
    local FILES="$4"

    if [ "$DRY_RUN" != "--dry-run" ]; then
        cat > "$DIR/README.md" << READMEEOF
# $TITLE

$DESC

## Dateien

$FILES

---
*Generiert: $(date +%Y-%m-%d)*
READMEEOF
    fi
    log "  ✓ README: $TITLE"
}

# Apps
generate_readme "$BASE/apps/pilot" "Mora02 Pilot Bot" \
    "Haupt-Chat-Interface der Creative Factory. Multi-Model (Qwen lokal, Claude API). Ersetzt alle vorherigen Bots (Assistant, Daily-Bot, Script-Bot, Social-Media-Bot)." \
    "- \`backend/\` — FastAPI App (app.py, config.py, baserow_client.py, llm_client.py)
- \`frontend/\` — HTML/JS Chat-UI (index.html, logo.png)"

generate_readme "$BASE/apps/script-runner" "Script Runner" \
    "FastAPI-Server der Media-Tools (Gifer, Typer, Clipper, Pexels, Pixabay) per HTTP-API bereitstellt. Wird vom Pilot Bot angesteuert." \
    "- \`backend/\` — FastAPI App (main.py, Dockerfile)
- \`frontend/\` — Standalone Script-Bot UI (index.html)"

generate_readme "$BASE/apps/knowledge-api" "Knowledge API" \
    "Flask-Wrapper für System-Knowledge Sync, Perplexity Web-Search, Claude Vision, Session-Summaries und Dify Knowledge Base Updates." \
    "- \`backend/\` — Flask App (knowledge-api.py, Dockerfile)
- Endpoints: /sync, /health, /perplexity, /vision, /ask-claude, /session-done, /export-sessions"

# Scripts — generate from existing docs where available
for tool in gifer pexels pixabay clipper typer; do
    # Check for existing doku in docs/system or project files
    DOKU=$(ls -t "$BASE/docs/system/"*"${tool}-doku"* "$BASE/docs/system/"*"${tool}"*"doku"* 2>/dev/null | head -1)
    if [ -n "$DOKU" ] && [ "$DRY_RUN" != "--dry-run" ]; then
        # Use existing doku as README basis
        cp "$DOKU" "$BASE/scripts/$tool/README.md"
        log "  ✓ README $tool (from existing doku)"
    else
        generate_readme "$BASE/scripts/$tool" "${tool^}" \
            "Media-Tool. Wird standalone oder via Script-Runner Container genutzt." \
            "- \`${tool}.py\` — Hauptscript"
    fi
done

generate_readme "$BASE/scripts/xray" "Mora02 X-Ray Scanner" \
    "System-Scanner: findet Secrets, mapped Dependencies, generiert Architektur-Diagramme." \
    "- \`mora02-xray.py\` — Scanner mit HTML-Dashboard und Report-Generierung"

generate_readme "$BASE/scripts/backup" "Backup Scripts" \
    "Borg-Backup Verwaltung (NFS Mount auf Synology NAS)." \
    "- \`backup-run.sh\` — Vollbackup starten
- \`backup-list.sh\` — Backups auflisten
- \`borg-prune-dryrun.sh\` — Prune simulieren
- \`borg-prune-live.sh\` — Prune ausführen"

generate_readme "$BASE/scripts/docker" "Docker Scripts" \
    "Shortcuts für Docker Compose Operationen." \
    "- \`docker-up.sh\` — Stack starten
- \`docker-down.sh\` — Stack stoppen
- \`docker-restart.sh\` — Stack neustarten
- \`docker-status.sh\` — Container-Status anzeigen"

generate_readme "$BASE/scripts/system" "System Scripts" \
    "Monitoring, Archivierung, Deployment-Hilfsmittel." \
    "- \`gpu-monitor.sh\` — GPU/VRAM Überwachung
- \`hardware-info.sh\` — System-Info Sammlung
- \`archive.sh\` — Stündliche Archivierung alter Outputs
- \`inject-html-keys.sh\` — API Keys in HTML-Frontends injizieren
- \`update-knowledge-base.sh\` — Dify Knowledge Base aktualisieren
- \`generate-session-summary.py\` — Session Summaries generieren
- \`export-sessions-to-knowledge.py\` — Sessions exportieren"

# ============================================================
# REPORT
# ============================================================
echo ""
echo "============================================================"
echo "  Stufe 1 FERTIG"
echo "============================================================"
echo ""
echo "Neue Struktur:"
echo "  apps/          $(find $BASE/apps -type f 2>/dev/null | wc -l) Dateien"
echo "  output/        $(find $BASE/output -type f 2>/dev/null | wc -l) Dateien"
echo "  knowledge/     $(find $BASE/knowledge -type f 2>/dev/null | wc -l) Dateien"
echo "  scripts/ (neu) $(find $BASE/scripts/gifer $BASE/scripts/pexels $BASE/scripts/pixabay $BASE/scripts/xray $BASE/scripts/backup $BASE/scripts/docker $BASE/scripts/system $BASE/scripts/_archive -type f 2>/dev/null | wc -l) Dateien in Unterordnern"
echo "  config/vpn/    $(find $BASE/config/vpn -type f 2>/dev/null | wc -l) Dateien"
echo ""
echo "Alte Struktur: UNVERÄNDERT (docs/, docker/, data/ etc.)"
echo ""
echo "Log: $LOG"
echo ""
echo "NÄCHSTER SCHRITT:"
echo "  1. Prüfe die neue Struktur: ls -la /opt/mora02/{apps,output,knowledge}"
echo "  2. Stichproben: diff /opt/mora02/docs/pilot/html/index.html /opt/mora02/apps/pilot/frontend/index.html"
echo "  3. Wenn alles OK → phase4-stufe2.sh ausführen"
echo "============================================================"
