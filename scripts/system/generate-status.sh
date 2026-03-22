#!/bin/bash
# =============================================================================
# Mora02 Status Generator
# Generiert aktuellen Projekt-Status aus Session-Logs
# =============================================================================
#
# Liest: /opt/mora02/knowledge/sessions/*.md
# Output: /opt/mora02/knowledge/archive/mora02-status-aktuell.md
#
# =============================================================================

set -e

SESSIONS_DIR="/opt/mora02/knowledge/sessions"
OUTPUT_DIR="/opt/mora02/knowledge/archive"
OUTPUT_FILE="${OUTPUT_DIR}/mora02-status-aktuell.md"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M')

echo "=========================================="
echo "Mora02 Status Generator"
echo "Started: $(date)"
echo "=========================================="

# Prüfe ob Sessions existieren
if [ ! -d "$SESSIONS_DIR" ] || [ -z "$(ls -A $SESSIONS_DIR/*.md 2>/dev/null)" ]; then
    echo "⚠ Keine Session-Logs gefunden in $SESSIONS_DIR"
    echo "  Erstelle erste Session mit: /opt/mora02/scripts/log-session.sh"
    exit 1
fi

# Zähle Sessions
SESSION_COUNT=$(ls -1 ${SESSIONS_DIR}/*.md 2>/dev/null | wc -l)
echo "→ Gefunden: $SESSION_COUNT Session-Logs"

# =============================================================================
# OUTPUT GENERIEREN
# =============================================================================

cat > "$OUTPUT_FILE" << EOF
# Mora02 Status

**Automatisch generiert:** ${TIMESTAMP}
**Quelle:** ${SESSION_COUNT} Session-Logs

---

## Letzte Aktivitäten

EOF

# Letzte 10 Sessions (neueste zuerst)
echo "→ Extrahiere letzte Sessions..."

for session_file in $(ls -t ${SESSIONS_DIR}/*.md 2>/dev/null | head -10); do
    # Extrahiere Metadaten aus YAML-Header
    DATUM=$(grep "^datum:" "$session_file" | cut -d: -f2- | tr -d ' ' || echo "?")
    KONTEXT=$(grep "^kontext:" "$session_file" | cut -d: -f2- | sed 's/^ *//' || echo "?")
    DAUER=$(grep "^dauer:" "$session_file" | cut -d: -f2- | sed 's/^ *//' || echo "?")
    
    echo "| ${DATUM} | ${KONTEXT} | ${DAUER} |" >> "$OUTPUT_FILE"
done

# Tabellen-Header einfügen (vor den Daten)
sed -i '/## Letzte Aktivitäten/a\\n| Datum | Was | Dauer |\n|-------|-----|-------|' "$OUTPUT_FILE"

cat >> "$OUTPUT_FILE" << 'EOF'

---

## Was wurde gemacht? (Letzte 5 Sessions)

EOF

# Extrahiere "Was haben wir gemacht?" aus den letzten 5 Sessions
for session_file in $(ls -t ${SESSIONS_DIR}/*.md 2>/dev/null | head -5); do
    FILENAME=$(basename "$session_file")
    DATUM=$(grep "^datum:" "$session_file" | cut -d: -f2- | tr -d ' ' || echo "?")
    KONTEXT=$(grep "^kontext:" "$session_file" | cut -d: -f2- | sed 's/^ *//' || echo "?")
    
    echo "### ${DATUM}: ${KONTEXT}" >> "$OUTPUT_FILE"
    echo "" >> "$OUTPUT_FILE"
    
    # Extrahiere den "Was haben wir gemacht?" Block
    sed -n '/^## Was haben wir gemacht/,/^## [^W]/p' "$session_file" | head -n -1 | tail -n +2 >> "$OUTPUT_FILE"
    
    echo "" >> "$OUTPUT_FILE"
done

cat >> "$OUTPUT_FILE" << 'EOF'

---

## Wichtige Entscheidungen (Letzte 5 Sessions)

EOF

# Extrahiere "Warum diese Entscheidungen?" aus den letzten 5 Sessions
for session_file in $(ls -t ${SESSIONS_DIR}/*.md 2>/dev/null | head -5); do
    DATUM=$(grep "^datum:" "$session_file" | cut -d: -f2- | tr -d ' ' || echo "?")
    
    # Extrahiere den "Warum" Block
    WARUM_BLOCK=$(sed -n '/^## Warum diese Entscheidungen/,/^## [^W]/p' "$session_file" | head -n -1 | tail -n +2)
    
    if [ -n "$WARUM_BLOCK" ] && [ "$WARUM_BLOCK" != "- " ]; then
        echo "**${DATUM}:**" >> "$OUTPUT_FILE"
        echo "$WARUM_BLOCK" >> "$OUTPUT_FILE"
        echo "" >> "$OUTPUT_FILE"
    fi
done

cat >> "$OUTPUT_FILE" << 'EOF'

---

## Offene Punkte

EOF

# Sammle alle "Offene Fragen" und "Nächster Schritt" aus letzten 3 Sessions
for session_file in $(ls -t ${SESSIONS_DIR}/*.md 2>/dev/null | head -3); do
    DATUM=$(grep "^datum:" "$session_file" | cut -d: -f2- | tr -d ' ' || echo "?")
    
    # Offene Fragen
    OFFEN=$(sed -n '/^## Offene Fragen/,/^## /p' "$session_file" | head -n -1 | tail -n +2 | grep -v "^- (keine)$" | grep -v "^$")
    if [ -n "$OFFEN" ]; then
        echo "**Aus ${DATUM}:**" >> "$OUTPUT_FILE"
        echo "$OFFEN" >> "$OUTPUT_FILE"
        echo "" >> "$OUTPUT_FILE"
    fi
done

cat >> "$OUTPUT_FILE" << 'EOF'

---

## Nächste Schritte

EOF

# Extrahiere "Nächster Schritt" aus der neuesten Session
LATEST_SESSION=$(ls -t ${SESSIONS_DIR}/*.md 2>/dev/null | head -1)
if [ -n "$LATEST_SESSION" ]; then
    sed -n '/^## Nächster Schritt/,/^---/p' "$LATEST_SESSION" | head -n -1 | tail -n +2 >> "$OUTPUT_FILE"
fi

cat >> "$OUTPUT_FILE" << EOF

---

## Live System Status

EOF

# Container-Status (wenn Docker verfügbar)
if command -v docker &> /dev/null; then
    CONTAINER_COUNT=$(docker ps -q 2>/dev/null | wc -l || echo "0")
    echo "**Container:** ${CONTAINER_COUNT} running" >> "$OUTPUT_FILE"
    echo "" >> "$OUTPUT_FILE"
    
    # Top Services
    echo "| Service | Status |" >> "$OUTPUT_FILE"
    echo "|---------|--------|" >> "$OUTPUT_FILE"
    for svc in dify-api baserow activepieces comfyui llama-qwen3; do
        STATUS=$(docker inspect -f '{{.State.Status}}' "$svc" 2>/dev/null || echo "not found")
        echo "| ${svc} | ${STATUS} |" >> "$OUTPUT_FILE"
    done
else
    echo "(Docker nicht verfügbar)" >> "$OUTPUT_FILE"
fi

cat >> "$OUTPUT_FILE" << EOF

---

_Generiert aus ${SESSION_COUNT} Session-Logs_
_Letzte Session: $(basename "$(ls -t ${SESSIONS_DIR}/*.md | head -1)" .md)_
EOF

echo ""
echo "=========================================="
echo "✓ Status generiert: $OUTPUT_FILE"
echo "  Sessions verarbeitet: $SESSION_COUNT"
echo "=========================================="
