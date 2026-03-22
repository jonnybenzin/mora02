#!/bin/bash
# Mora02 – docker-compose.yml History aus Borg Backups rekonstruieren
# Erstellt: 2026-02-09

REPO="/home/jonnybenzin/synology-backup"
COMPOSE_PATH="opt/mora02/docker/docker-compose.yml"
OUTPUT_DIR="/opt/mora02/knowledge/changelog"
SNAPSHOTS_DIR="$OUTPUT_DIR/compose-snapshots"
DIFFS_DIR="$OUTPUT_DIR/diffs"

echo "=== Mora02 Borg Compose History ==="
echo ""

# Verzeichnisse anlegen
mkdir -p "$SNAPSHOTS_DIR" "$DIFFS_DIR"

# Alle Snapshots holen
echo "[1/4] Borg Snapshots auflisten..."
SNAPSHOTS=$(borg list --short "$REPO" | sort)
TOTAL=$(echo "$SNAPSHOTS" | wc -l)
echo "      $TOTAL Snapshots gefunden."
echo ""

# Compose aus jedem Snapshot extrahieren und hashen
echo "[2/4] docker-compose.yml aus jedem Snapshot extrahieren und hashen..."
PREV_HASH=""
PREV_SNAPSHOT=""
PREV_FILE=""
CHANGE_COUNT=0
COUNT=0

while IFS= read -r snapshot; do
    COUNT=$((COUNT + 1))
    SAFE_TS=$(echo "$snapshot" | sed 's/system-backup-//')

    # Compose extrahieren
    CONTENT=$(borg extract --stdout "${REPO}::${snapshot}" "$COMPOSE_PATH" 2>/dev/null)

    if [ -z "$CONTENT" ]; then
        printf "\r  [%d/%d] %s - keine compose gefunden, skip" "$COUNT" "$TOTAL" "$snapshot"
        continue
    fi

    # Hash berechnen
    CURRENT_HASH=$(echo "$CONTENT" | md5sum | cut -d' ' -f1)

    if [ "$CURRENT_HASH" != "$PREV_HASH" ]; then
        CHANGE_COUNT=$((CHANGE_COUNT + 1))

        # Compose-Datei speichern
        OUTFILE="$SNAPSHOTS_DIR/${SAFE_TS}.yml"
        echo "$CONTENT" > "$OUTFILE"

        # Diff erzeugen (wenn nicht erster)
        if [ -n "$PREV_FILE" ]; then
            DIFF_NAME="${PREV_SNAPSHOT}__to__${SAFE_TS}.diff"
            diff -u "$PREV_FILE" "$OUTFILE" > "$DIFFS_DIR/$DIFF_NAME" 2>/dev/null
            ADDED=$(grep -c '^+[^+]' "$DIFFS_DIR/$DIFF_NAME" 2>/dev/null || echo 0)
            REMOVED=$(grep -c '^-[^-]' "$DIFFS_DIR/$DIFF_NAME" 2>/dev/null || echo 0)
            printf "\r  [%d/%d] ✓ ÄNDERUNG #%d: %s (+%s/-%s Zeilen)          \n" "$COUNT" "$TOTAL" "$CHANGE_COUNT" "$SAFE_TS" "$ADDED" "$REMOVED"
        else
            printf "\r  [%d/%d] ✓ ÄNDERUNG #%d: %s (Initial)                  \n" "$COUNT" "$TOTAL" "$CHANGE_COUNT" "$SAFE_TS"
        fi

        PREV_HASH="$CURRENT_HASH"
        PREV_SNAPSHOT="$SAFE_TS"
        PREV_FILE="$OUTFILE"
    else
        printf "\r  [%d/%d] %s - keine Änderung" "$COUNT" "$TOTAL" "$snapshot"
    fi

done <<< "$SNAPSHOTS"

echo ""
echo ""
echo "[3/4] Zusammenfassung:"
echo "      $TOTAL Snapshots durchsucht"
echo "      $CHANGE_COUNT Änderungen gefunden"
echo "      Snapshots: $SNAPSHOTS_DIR/"
echo "      Diffs:     $DIFFS_DIR/"

# Übersicht generieren
echo ""
echo "[4/4] Übersicht generieren..."

OVERVIEW="$OUTPUT_DIR/changes-overview.txt"
echo "# Mora02 docker-compose.yml Änderungen" > "$OVERVIEW"
echo "# Rekonstruiert aus Borg Backups am $(date '+%Y-%m-%d %H:%M')" >> "$OVERVIEW"
echo "# $CHANGE_COUNT Änderungen in $TOTAL Snapshots" >> "$OVERVIEW"
echo "" >> "$OVERVIEW"

for f in "$SNAPSHOTS_DIR"/*.yml; do
    TS=$(basename "$f" .yml)
    CONTAINERS=$(grep -c 'container_name:' "$f" 2>/dev/null || echo "?")
    echo "$TS  |  ~${CONTAINERS} container" >> "$OVERVIEW"
done

cat "$OVERVIEW"
echo ""
echo "=== Fertig! ==="
