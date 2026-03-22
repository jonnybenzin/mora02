#!/bin/bash
# =============================================================================
# Mora02 Strategist Knowledge Base Update Script
# Generiert Knowledge Base für mora02_strategist Agent
# =============================================================================

set -e

TIMESTAMP=$(date +%Y%m%d_%H%M)
DOCS_DIR="/opt/mora02/knowledge/handbook"
OUTPUT_DIR="/opt/mora02/data/knowledge-base"
OUTPUT_FILE="${OUTPUT_DIR}/mora02-strategist-${TIMESTAMP}.md"
LATEST_LINK="${OUTPUT_DIR}/mora02-strategist-latest.md"
STATUS_FILE="/opt/mora02/data/strategist-sync-status.txt"

# Erstelle Output-Verzeichnis falls nicht vorhanden
mkdir -p "$OUTPUT_DIR"

echo "=========================================="
echo "Mora02 Strategist Knowledge Base Update"
echo "Started: $(date)"
echo "=========================================="

# =============================================================================
# HEADER
# =============================================================================

cat > "$OUTPUT_FILE" << EOF
# Mora02 Strategist Knowledge Base

**Automatisch generiert:** $(date '+%Y-%m-%d %H:%M:%S')
**Zweck:** Kontext für strategische Beratung (Content + System)

---

EOF

# =============================================================================
# HELPER FUNCTION
# =============================================================================

add_latest_doc() {
    local pattern=$1
    local title=$2
    local file=$(ls -t ${DOCS_DIR}/*${pattern}*.md 2>/dev/null | head -1)
    
    if [ -n "$file" ] && [ -f "$file" ]; then
        echo "  ✓ ${title}: $(basename "$file")"
        echo -e "\n## ${title}\n" >> "$OUTPUT_FILE"
        echo "_Quelle: $(basename "$file")_" >> "$OUTPUT_FILE"
        echo "" >> "$OUTPUT_FILE"
        cat "$file" >> "$OUTPUT_FILE"
        echo -e "\n---\n" >> "$OUTPUT_FILE"
        return 0
    else
        echo "  ⚠ ${title}: nicht gefunden (Pattern: *${pattern}*.md)"
        return 1
    fi
}

add_specific_doc() {
    local file=$1
    local title=$2
    
    if [ -f "$file" ]; then
        echo "  ✓ ${title}: $(basename "$file")"
        echo -e "\n## ${title}\n" >> "$OUTPUT_FILE"
        echo "_Quelle: $(basename "$file")_" >> "$OUTPUT_FILE"
        echo "" >> "$OUTPUT_FILE"
        cat "$file" >> "$OUTPUT_FILE"
        echo -e "\n---\n" >> "$OUTPUT_FILE"
        return 0
    else
        echo "  ⚠ ${title}: nicht gefunden ($file)"
        return 1
    fi
}

# =============================================================================
# 1. PROJEKT-STATUS (Roadmap + Backlog)
# =============================================================================

echo "→ Sammle Projekt-Status..."

cat >> "$OUTPUT_FILE" << 'EOF'

# TEIL 1: PROJEKT-STATUS

Diese Dokumente zeigen den aktuellen Stand des Mora02 Projekts.

EOF

add_latest_doc "roadmap-aktuell" "Aktuelle Roadmap"
add_latest_doc "backlog" "Backlog"

# =============================================================================
# 2. SYSTEM-ÜBERBLICK (für Architektur-Beratung)
# =============================================================================

echo "→ Sammle System-Überblick..."

cat >> "$OUTPUT_FILE" << 'EOF'

# TEIL 2: SYSTEM-ÜBERBLICK

Technischer Kontext für Architektur-Beratung.

EOF

add_latest_doc "betriebshandbuch" "Betriebshandbuch"

# Container-Übersicht (live)
echo "  → Generiere Container-Status..."
cat >> "$OUTPUT_FILE" << EOF

## Aktive Container (Live)

_Generiert: $(date '+%Y-%m-%d %H:%M:%S')_

| Container | Status | Ports |
|-----------|--------|-------|
EOF

docker ps --format "| {{.Names}} | {{.Status}} | {{.Ports}} |" 2>/dev/null >> "$OUTPUT_FILE" || echo "| (Docker nicht erreichbar) | - | - |" >> "$OUTPUT_FILE"

echo -e "\n---\n" >> "$OUTPUT_FILE"

# =============================================================================
# 3. CONTENT-STRATEGIE (für Content-Beratung)
# =============================================================================

echo "→ Sammle Content-Strategie..."

cat >> "$OUTPUT_FILE" << 'EOF'

# TEIL 3: CONTENT-STRATEGIE

Regeln und Guidelines für Social Media Content.

EOF

add_latest_doc "linkedin-content-strategy" "LinkedIn Content Strategy"
add_latest_doc "socialmedia-implementation-plan" "Social Media Implementation Plan"
add_latest_doc "social-media-bot-dokumentation" "Social Media Bot Dokumentation"

# =============================================================================
# 4. ZUSAMMENFASSUNG FÜR SCHNELLEN ZUGRIFF
# =============================================================================

echo "→ Generiere Schnellreferenz..."

cat >> "$OUTPUT_FILE" << 'EOF'

# TEIL 4: SCHNELLREFERENZ

## Content Pillars
- **60%** Building in Public (Mora02, Tech, Behind-the-scenes)
- **20%** Critical Perspectives (AI Hype, Ownership, Big Tech)
- **20%** Personal/Philosophical

## Positionierung
"AI systems for creatives — the right way."
- Lokal, Open Source, Kontrolle behalten
- Anti-Big-Tech-Abhängigkeit
- Fun over Efficiency

## Voice Keywords
- Direkt, opinioniert, selbstironisch
- Schreiben wie sprechen
- Begeisterung für nerdy Details
- Unsicherheit zugeben wenn echt

## Red Flags (IMMER vermeiden)
- ❌ Humble-bragging
- ❌ Credential-leading
- ❌ Corporate buzzwords
- ❌ Hashtags
- ❌ Employer mentions (Agentur nicht namentlich)
- ❌ Engagement bait

## Drei Grundprinzipien Mora02
1. **Lokal** — Keine Cloud-Abhängigkeiten (außer bewusst 20%)
2. **Open Source** — Keine proprietären Tools
3. **Portabel** — Muss auf anderem System reproduzierbar sein

EOF

# =============================================================================
# ABSCHLUSS
# =============================================================================

# Symlink auf neueste Version
ln -sf "$OUTPUT_FILE" "$LATEST_LINK"

# Zähle Dokumente
DOC_COUNT=$(grep -c "^## " "$OUTPUT_FILE" 2>/dev/null || echo "0")

# Status-Datei aktualisieren
cat > "$STATUS_FILE" << EOF
LAST_SYNC=$(date -Iseconds)
LAST_SYNC_READABLE=$(date '+%Y-%m-%d %H:%M:%S')
OUTPUT_FILE=$OUTPUT_FILE
DOC_COUNT=$DOC_COUNT
EOF

# Zusammenfassung
echo ""
echo "=========================================="
echo "✓ Strategist Knowledge Base aktualisiert!"
echo "  Output: $OUTPUT_FILE"
echo "  Symlink: $LATEST_LINK"
echo "  Sections: $DOC_COUNT"
echo "=========================================="
echo ""
echo "Nächster Schritt:"
echo "  1. Dify öffnen: http://mora02.local:8090"
echo "  2. Knowledge → Create Knowledge Base → 'mora02-strategist-knowledge'"
echo "  3. Upload: $LATEST_LINK"
echo ""

# Cleanup: Behalte nur die letzten 5 Versionen
ls -t ${OUTPUT_DIR}/mora02-strategist-*.md 2>/dev/null | tail -n +6 | xargs rm -f 2>/dev/null || true

exit 0
