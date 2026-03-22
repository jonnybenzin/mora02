#!/bin/bash
# =============================================================================
# Mora02 Knowledge Base Update Script - LIVE VERSION
# Generiert aktuelle System-Daten für den System-Assistant
# =============================================================================

set -e

TIMESTAMP=$(date +%Y%m%d_%H%M)
DOCS_DIR="/opt/mora02/knowledge/handbook"
DOCKER_DIR="/opt/mora02/docker"
SCRIPTS_DIR="/opt/mora02/scripts"
OUTPUT_DIR="/opt/mora02/data/knowledge-base"
OUTPUT_FILE="${OUTPUT_DIR}/mora02-knowledge-${TIMESTAMP}.md"
LATEST_LINK="${OUTPUT_DIR}/mora02-knowledge-latest.md"
STATUS_FILE="/opt/mora02/data/knowledge-sync-status.txt"

# Erstelle Output-Verzeichnis falls nicht vorhanden
mkdir -p "$OUTPUT_DIR"

echo "=========================================="
echo "Mora02 Knowledge Base Update (LIVE)"
echo "Started: $(date)"
echo "=========================================="

# =============================================================================
# HEADER
# =============================================================================

cat > "$OUTPUT_FILE" << EOF
# Mora02 Knowledge Base

**Automatisch generiert:** $(date '+%Y-%m-%d %H:%M:%S')
**Typ:** Live-Daten + Dokumentation

---

EOF

# =============================================================================
# 1. LIVE SYSTEM STATUS
# =============================================================================

echo "→ Generiere Live-System-Status..."

cat >> "$OUTPUT_FILE" << 'EOF'
# LIVE SYSTEM STATUS

## Hardware
EOF

# CPU Info
echo "" >> "$OUTPUT_FILE"
CPU_MODEL=$(lscpu | grep -i -E 'Model name|Modellname' | cut -d: -f2 | xargs)
echo "**CPU:** ${CPU_MODEL}" >> "$OUTPUT_FILE"
echo "**Cores:** $(nproc)" >> "$OUTPUT_FILE"

# RAM Info
TOTAL_RAM=$(free -h | awk '/Speicher/ {print $2}')
USED_RAM=$(free -h | awk '/Speicher/ {print $3}')
echo "**RAM:** ${USED_RAM} / ${TOTAL_RAM}" >> "$OUTPUT_FILE"

# GPU Info
if command -v nvidia-smi &> /dev/null; then
    GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)
    GPU_VRAM_USED=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader 2>/dev/null | head -1)
    GPU_VRAM_TOTAL=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader 2>/dev/null | head -1)
    GPU_VRAM_FREE=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader 2>/dev/null | head -1)
    GPU_UTIL=$(nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader 2>/dev/null | head -1)
    
    echo "" >> "$OUTPUT_FILE"
    echo "**GPU:** ${GPU_NAME}" >> "$OUTPUT_FILE"
    echo "**VRAM:** ${GPU_VRAM_USED} / ${GPU_VRAM_TOTAL} (${GPU_VRAM_FREE} frei)" >> "$OUTPUT_FILE"
    echo "**GPU Auslastung:** ${GPU_UTIL}" >> "$OUTPUT_FILE"
else
    echo "**GPU:** nvidia-smi nicht verfügbar" >> "$OUTPUT_FILE"
fi

# Disk Info
echo "" >> "$OUTPUT_FILE"
echo "**Speicherplatz /opt/mora02:**" >> "$OUTPUT_FILE"
echo '```' >> "$OUTPUT_FILE"
df -h /opt/mora02 2>/dev/null | tail -1 >> "$OUTPUT_FILE"
echo '```' >> "$OUTPUT_FILE"

# Uptime
echo "" >> "$OUTPUT_FILE"
echo "**System Uptime:** $(uptime -p)" >> "$OUTPUT_FILE"

# =============================================================================
# 2. DOCKER CONTAINER STATUS (LIVE)
# =============================================================================

echo "→ Sammle Docker-Status..."

cat >> "$OUTPUT_FILE" << 'EOF'

## Docker Container (Live)

EOF

CONTAINER_COUNT=$(docker ps -q 2>/dev/null | wc -l)
echo "**Aktive Container:** ${CONTAINER_COUNT}" >> "$OUTPUT_FILE"
echo "" >> "$OUTPUT_FILE"

echo '```' >> "$OUTPUT_FILE"
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null >> "$OUTPUT_FILE" || echo "Docker nicht erreichbar" >> "$OUTPUT_FILE"
echo '```' >> "$OUTPUT_FILE"

# =============================================================================
# 3. PORT-ÜBERSICHT (LIVE aus Docker)
# =============================================================================

echo "→ Generiere Port-Übersicht..."

cat >> "$OUTPUT_FILE" << 'EOF'

## Port-Übersicht (Live)

| Port | Container | Status |
|------|-----------|--------|
EOF

docker ps --format "{{.Ports}}\t{{.Names}}\t{{.Status}}" 2>/dev/null | \
while IFS=$'\t' read -r ports name status; do
    # Extrahiere Host-Port aus Format wie "0.0.0.0:8080->8080/tcp"
    echo "$ports" | tr ',' '\n' | while read -r port_mapping; do
        if [[ "$port_mapping" =~ ([0-9]+)-\> ]]; then
            host_port="${BASH_REMATCH[1]}"
            # Status kürzen
            short_status=$(echo "$status" | cut -d' ' -f1-2)
            echo "| ${host_port} | ${name} | ${short_status} |"
        fi
    done
done >> "$OUTPUT_FILE"

# =============================================================================
# 4. VERZEICHNISSTRUKTUR (LIVE)
# =============================================================================

echo "→ Generiere Verzeichnisstruktur..."

cat >> "$OUTPUT_FILE" << 'EOF'

## Verzeichnisstruktur (Live)

### Hauptverzeichnis /opt/mora02
EOF

echo '```' >> "$OUTPUT_FILE"
if command -v tree &> /dev/null; then
    tree -L 2 -d /opt/mora02 --noreport 2>/dev/null >> "$OUTPUT_FILE"
else
    find /opt/mora02 -maxdepth 2 -type d 2>/dev/null | head -50 >> "$OUTPUT_FILE"
fi
echo '```' >> "$OUTPUT_FILE"

# Scripts auflisten
cat >> "$OUTPUT_FILE" << 'EOF'

### Verfügbare Scripts
EOF
echo '```' >> "$OUTPUT_FILE"
ls -1 /opt/mora02/scripts/*.sh /opt/mora02/scripts/*.py 2>/dev/null | xargs -n1 basename >> "$OUTPUT_FILE" || echo "Keine Scripts gefunden" >> "$OUTPUT_FILE"
echo '```' >> "$OUTPUT_FILE"

# Docs/System auflisten (nur neueste 15)
cat >> "$OUTPUT_FILE" << 'EOF'

### System-Dokumentation (neueste 15)
EOF
echo '```' >> "$OUTPUT_FILE"
ls -1t ${DOCS_DIR}/*.md 2>/dev/null | head -15 | xargs -n1 basename >> "$OUTPUT_FILE" || echo "Keine Docs gefunden" >> "$OUTPUT_FILE"
echo '```' >> "$OUTPUT_FILE"

# =============================================================================
# 5. LLM STATUS
# =============================================================================

echo "→ Prüfe LLM-Status..."

cat >> "$OUTPUT_FILE" << 'EOF'

## LLM Status

EOF

# Prüfe ob LLM erreichbar
if curl -s --max-time 2 http://host.docker.internal:8080/health > /dev/null 2>&1; then
    echo "**LLM API:** ✅ Online (Port 8080)" >> "$OUTPUT_FILE"
    
    # Versuche Modell-Info zu holen
    MODEL_INFO=$(curl -s --max-time 2 http://host.docker.internal:8080/v1/models 2>/dev/null | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4)
    if [ -n "$MODEL_INFO" ]; then
        echo "**Modell:** ${MODEL_INFO}" >> "$OUTPUT_FILE"
    fi
else
    echo "**LLM API:** ❌ Nicht erreichbar" >> "$OUTPUT_FILE"
fi

# =============================================================================
# 6. SERVICE HEALTH CHECKS
# =============================================================================

echo "→ Führe Health Checks durch..."

cat >> "$OUTPUT_FILE" << 'EOF'

## Service Health Checks

| Service | Port | Status |
|---------|------|--------|
EOF

check_service() {
    local name=$1
    local container=$2
    local port=$3
    
    # Prüfe ob Container läuft und healthy ist
    local status=$(docker inspect -f '{{.State.Status}}' "$container" 2>/dev/null)
    local health=$(docker inspect -f '{{.State.Health.Status}}' "$container" 2>/dev/null)
    
    if [ "$status" = "running" ]; then
        if [ "$health" = "healthy" ] || [ "$health" = "" ]; then
            echo "| ${name} | ${port} | ✅ Online |"
        else
            echo "| ${name} | ${port} | ⚠️ ${health} |"
        fi
    else
        echo "| ${name} | ${port} | ❌ Offline |"
    fi
}
check_service "Dify Web" "dify-web" 8090 >> "$OUTPUT_FILE"
check_service "Dify API" "dify-api" 8091 >> "$OUTPUT_FILE"
check_service "Baserow" "baserow" 8085 >> "$OUTPUT_FILE"
check_service "Activepieces" "activepieces" 8089 >> "$OUTPUT_FILE"
check_service "ComfyUI" "comfyui" 8188 >> "$OUTPUT_FILE"
check_service "SearXNG" "searxng" 8094 >> "$OUTPUT_FILE"
check_service "Knowledge API" "knowledge-api" 8095 >> "$OUTPUT_FILE"
check_service "Postiz" "postiz" 8100 >> "$OUTPUT_FILE"
check_service "Penpot" "penpot-frontend" 8101 >> "$OUTPUT_FILE"
check_service "Excalidraw" "excalidraw" 8102 >> "$OUTPUT_FILE"
check_service "nginx Images" "nginx-images" 8092 >> "$OUTPUT_FILE"

# =============================================================================
# 7. CORE DOKUMENTATION (aus Dateien)
# =============================================================================

echo "→ Sammle Core-Dokumentation..."

cat >> "$OUTPUT_FILE" << 'EOF'

---

# DOKUMENTATION

EOF

# Funktion: Neueste Datei mit Pattern finden und einfügen
add_latest_doc() {
    local pattern=$1
    local title=$2
    local latest=$(ls -t ${DOCS_DIR}/*${pattern}*.md 2>/dev/null | head -1)
    
    if [ -f "$latest" ]; then
        echo "  ✓ $title: $(basename $latest)"
        echo -e "\n## $title\n" >> "$OUTPUT_FILE"
        echo "*Quelle: $(basename $latest)*" >> "$OUTPUT_FILE"
        echo "" >> "$OUTPUT_FILE"
        cat "$latest" >> "$OUTPUT_FILE"
        echo -e "\n---\n" >> "$OUTPUT_FILE"
    else
        echo "  ⚠ $title: nicht gefunden"
    fi
}

add_latest_doc "roadmap-aktuell" "Roadmap"
add_latest_doc "backlog" "Backlog"
add_latest_doc "betriebshandbuch" "Betriebshandbuch"

# Neueste 5 AP-Dokumentationen
echo "→ Sammle neueste AP-Dokumentationen..."

cat >> "$OUTPUT_FILE" << 'EOF'

## Neueste Arbeitspakete (AP)

EOF

AP_COUNT=0
ls -t ${DOCS_DIR}/*ap[0-9]*.md 2>/dev/null | head -5 | while read ap_file; do
    if [ -f "$ap_file" ]; then
        AP_NAME=$(basename "$ap_file")
        echo "  ✓ AP: ${AP_NAME}"
        echo -e "\n### ${AP_NAME}\n" >> "$OUTPUT_FILE"
        cat "$ap_file" >> "$OUTPUT_FILE"
        echo -e "\n---\n" >> "$OUTPUT_FILE"
    fi
done

echo "  → ${AP_COUNT} AP-Dokus eingebunden"

# =============================================================================
# 8. KRITISCHE PFADE REFERENZ
# =============================================================================

cat >> "$OUTPUT_FILE" << 'EOF'

## Kritische Pfade (Referenz)

| Was | Pfad |
|-----|------|
| Docker Compose | `/opt/mora02/docker/docker-compose.yml` |
| System-Docs | `/opt/mora02/knowledge/handbook/` |
| LLM Modelle | `/opt/mora02/ai_models/llama_cpp/` |
| ComfyUI Modelle | `/opt/mora02/ai_models/comfyui/` |
| ComfyUI Output | `/opt/mora02/output/_default/comfyui/` |
| Scripts | `/opt/mora02/scripts/` |
| Knowledge Base | `/opt/mora02/data/knowledge-base/` |
| Backup Mount | `/home/jonnybenzin/synology-backup` |

EOF

# =============================================================================
# ABSCHLUSS
# =============================================================================

# Symlink auf neueste Version
ln -sf "$OUTPUT_FILE" "$LATEST_LINK"

# Status-Datei aktualisieren
cat > "$STATUS_FILE" << EOF
LAST_SYNC=$(date -Iseconds)
LAST_SYNC_READABLE=$(date '+%Y-%m-%d %H:%M:%S')
DOCS_COUNT=$(find "$DOCS_DIR" -name "*.md" 2>/dev/null | wc -l)
OUTPUT_FILE=$OUTPUT_FILE
CONTAINER_COUNT=$CONTAINER_COUNT
GPU_VRAM_FREE=${GPU_VRAM_FREE:-"unknown"}
EOF

# Zusammenfassung
echo ""
echo "=========================================="
echo "✓ Knowledge Base aktualisiert!"
echo "  Output: $OUTPUT_FILE"
echo "  Symlink: $LATEST_LINK"
echo "  Docs: $(find "$DOCS_DIR" -name "*.md" 2>/dev/null | wc -l)"
echo "  Container: $CONTAINER_COUNT"
echo "  VRAM frei: ${GPU_VRAM_FREE:-unknown}"
echo "=========================================="

# Cleanup: Behalte nur die letzten 7 Versionen
ls -t ${OUTPUT_DIR}/mora02-knowledge-*.md 2>/dev/null | tail -n +8 | xargs rm -f 2>/dev/null || true

exit 0
