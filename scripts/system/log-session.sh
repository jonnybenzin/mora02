#!/bin/bash
# =============================================================================
# Mora02 Session Logger
# Erstellt standardisierte Session-Dokumentation
# =============================================================================
#
# Nutzung: 
#   ./log-session.sh "Kurze Beschreibung der Session"
#
# Oder interaktiv:
#   ./log-session.sh
#
# =============================================================================

set -e

SESSIONS_DIR="/opt/mora02/knowledge/sessions"
TIMESTAMP=$(date +%y%m%d%H%M)
DATE_READABLE=$(date '+%Y-%m-%d')
TIME_READABLE=$(date '+%H:%M')

# Erstelle Sessions-Verzeichnis falls nicht vorhanden
mkdir -p "$SESSIONS_DIR"

# Session-Beschreibung
if [ -n "$1" ]; then
    DESCRIPTION="$1"
else
    echo "Session-Beschreibung (kurz):"
    read DESCRIPTION
fi

# Safe filename aus Beschreibung
SAFE_DESC=$(echo "$DESCRIPTION" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g' | sed 's/--*/-/g' | cut -c1-40)
FILENAME="${TIMESTAMP}_${SAFE_DESC}.md"
FILEPATH="${SESSIONS_DIR}/${FILENAME}"

# Template erstellen
cat > "$FILEPATH" << EOF
---
datum: ${DATE_READABLE}
zeit: ${TIME_READABLE}
dauer: ~_h
kontext: ${DESCRIPTION}
---

## Was haben wir gemacht?

1. **[Hauptaktion 1]**
   - Detail
   - Detail

2. **[Hauptaktion 2]**
   - Detail

## Warum diese Entscheidungen?

- **[Entscheidung 1]:** [Begründung]
- **[Entscheidung 2]:** [Begründung]

## Änderungen an Dateien

| Datei | Änderung |
|-------|----------|
| /opt/mora02/... | Neu erstellt / Geändert / Gelöscht |

## Offene Fragen / Probleme

- (keine)

## Nächster Schritt

- [ ] ...

---
_Session dokumentiert: ${DATE_READABLE} ${TIME_READABLE}_
EOF

echo ""
echo "✓ Session-Log erstellt: $FILEPATH"
echo ""
echo "Jetzt ausfüllen:"
echo "  nano $FILEPATH"
echo ""
echo "Oder mit VS Code:"
echo "  code $FILEPATH"
