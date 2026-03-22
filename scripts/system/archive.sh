#!/bin/bash
TARGET_DIR="$1"
ARCHIVE_DIR="$TARGET_DIR/x_archiv"
KEEP=10

if [ ! -d "$TARGET_DIR" ]; then
    echo "Fehler: $TARGET_DIR existiert nicht"
    exit 1
fi

mkdir -p "$ARCHIVE_DIR"

# ÄNDERUNG: -type d für Ordner, -mindepth 1 um . zu ignorieren, exclude _archiv
find "$TARGET_DIR" -maxdepth 1 -mindepth 1 -type d -not -name "x_archiv" -printf '%T@ %p\n' | \
    sort -rn | \
    tail -n +$((KEEP + 1)) | \
    cut -d' ' -f2- | \
    while read -r entry; do
        echo "Archiviere Ordner: $(basename "$entry")"
        mv "$entry" "$ARCHIVE_DIR/"
    done

