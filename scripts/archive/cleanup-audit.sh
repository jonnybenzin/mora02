#!/bin/bash
# cleanup-audit — scannt /opt/mora02/ nach Aufraeum-Verdachts-Kandidaten.
# Schreibt einen Markdown-Bericht mit Pfad, mtime, Groesse und Verdachts-Grund.
#
# Aufruf:
#   cleanup-audit.sh                 # Bericht nach stdout
#   cleanup-audit.sh --out FILE.md   # Bericht in Datei
#
# Mechanik:
#   - Pattern-Match auf Namens-Stellen die archiv-verdaechtig sind
#   - mtime > 180 Tage als Hinweis (nicht als hartes Kriterium)
#   - bekannte verwaiste Stellen aus dem ADR-021-Kontext namentlich gelistet
#
# Output ist informativ, nicht automatisch loescht. Klassifikation und
# Archive-Aktion bleiben manuell ueber archive-to.sh.

set -e

REPO_ROOT="/opt/mora02"
STALE_DAYS=180

OUTPUT_FILE=""
if [[ "$1" == "--out" && -n "$2" ]]; then
    OUTPUT_FILE="$2"
fi

write() {
    if [[ -n "$OUTPUT_FILE" ]]; then
        echo "$@" >> "$OUTPUT_FILE"
    else
        echo "$@"
    fi
}

if [[ -n "$OUTPUT_FILE" ]]; then
    > "$OUTPUT_FILE"
fi

# Pretty-format a path with mtime and size
describe_path() {
    local p="$1"
    if [[ -e "$p" ]]; then
        local mtime
        mtime=$(stat -c %y "$p" 2>/dev/null | cut -d' ' -f1)
        local size
        size=$(du -sh "$p" 2>/dev/null | cut -f1)
        echo "${p#$REPO_ROOT/} — last-modified: $mtime, size: $size"
    else
        echo "${p#$REPO_ROOT/} — (not found)"
    fi
}

write "# Cleanup-Audit — $(date -Iseconds)"
write ""
write "Verdachts-Kandidaten fuer Aufraeumen via [archive-to.sh](./README.md)."
write "Output ist informativ, keine automatische Aktion. Bitte pro Eintrag entscheiden:"
write "behalten, archivieren, loeschen, oder unklar (für Folge-Diskussion)."
write ""

# --- 0. Top-Level-Inventur ---
write "## Top-Level-Inventur"
write ""
write "Alle Top-Level-Verzeichnisse mit Groesse, letztem mtime und Item-Count."
write "Schnell-Ueberblick was im Repo wohnt — fuer die manuelle Bewertung jenseits"
write "der Pattern-basierten Heuristiken."
write ""
write "| Verzeichnis | Groesse | Last-modified | Items |"
write "|---|---|---|---|"

while IFS= read -r p; do
    [[ -z "$p" ]] && continue
    name=$(basename "$p")
    [[ "$name" == ".git" ]] && continue
    if [[ -d "$p" ]]; then
        size=$(du -sh "$p" 2>/dev/null | cut -f1)
        mtime=$(stat -c %y "$p" 2>/dev/null | cut -d' ' -f1)
        items=$(find "$p" -mindepth 1 -maxdepth 1 2>/dev/null | wc -l)
        write "| ${name}/ | $size | $mtime | $items |"
    fi
done < <(find "$REPO_ROOT" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort)

write ""

# --- 0b. Container-spezifische Subdirs unter docker/ und volumes/ ---
write "## docker/ und volumes/ Subdirs"
write ""
write "Container-spezifische Verzeichnisse — vor allem fuer Phase-out-Container"
write "wie activepieces oder dify relevant. Zeigt welche Daten- und Config-Stellen"
write "an einem aufgeloesten oder im Phase-out befindlichen Service haengen."
write ""
write "| Verzeichnis | Groesse | Last-modified |"
write "|---|---|---|"

for parent in "$REPO_ROOT/docker" "$REPO_ROOT/volumes"; do
    [[ ! -d "$parent" ]] && continue
    while IFS= read -r p; do
        [[ -z "$p" ]] && continue
        size=$(du -sh "$p" 2>/dev/null | cut -f1)
        mtime=$(stat -c %y "$p" 2>/dev/null | cut -d' ' -f1)
        rel="${p#$REPO_ROOT/}"
        write "| $rel | $size | $mtime |"
    done < <(find "$parent" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort)
done

write ""

# --- 1. Pattern-basierte Verzeichnisse ---
write "## Pattern-basiert: archiv-verdaechtige Namen"
write ""
write "Verzeichnisse mit Namens-Mustern \`_archive\`, \`_old\`, \`backup*\`, \`*pre-phase*\`."
write ""

while IFS= read -r p; do
    [[ -z "$p" ]] && continue
    write "- $(describe_path "$p")"
done < <(find "$REPO_ROOT" \
    -mindepth 1 -maxdepth 4 \
    \( -name '_archive' -o -name '*_old' -o -name 'backup*' -o -name '*pre-phase*' \) \
    -not -path "$REPO_ROOT/_archive*" \
    -not -path "$REPO_ROOT/volumes/*" \
    -not -path "$REPO_ROOT/output/*" \
    -not -path "$REPO_ROOT/.git/*" \
    -not -path "*/venv*/*" \
    -not -path "*/node_modules/*" \
    -not -path "*/__pycache__/*" \
    2>/dev/null | sort -u)

write ""

# --- 2. __pycache__-Reste ---
write "## __pycache__-Reste"
write ""
write "Bytecode-Verzeichnisse von Python — meist harmlos, koennen aber zeigen"
write "wo Code lief der vielleicht nicht mehr gebraucht wird."
write ""

while IFS= read -r p; do
    [[ -z "$p" ]] && continue
    write "- $(describe_path "$p")"
done < <(find "$REPO_ROOT/apps" "$REPO_ROOT/scripts" "$REPO_ROOT/lib" \
    -type d -name '__pycache__' \
    -not -path "$REPO_ROOT/.git/*" \
    -not -path "*/venv*/*" \
    2>/dev/null | sort -u)

write ""

# --- 3. Stale top-level entries (>180 Tage unverändert) ---
write "## Stale: Top-Level-Eintraege aelter als ${STALE_DAYS} Tage"
write ""
write "Verzeichnisse die seit ueber sechs Monaten nicht angefasst wurden — Verdacht,"
write "dass sie aus Pre-Refactor-Zeiten stammen und nicht mehr gebraucht werden."
write ""

while IFS= read -r p; do
    [[ -z "$p" ]] && continue
    write "- $(describe_path "$p")"
done < <(find "$REPO_ROOT" -mindepth 1 -maxdepth 1 \
    -mtime +${STALE_DAYS} \
    -not -name '.git' \
    -not -name '_archive' \
    2>/dev/null | sort -u)

write ""

# --- 4. Git-bekannte deleted Pfade ---
write "## Git-deleted: im Working Tree fehlend, im Index noch da"
write ""
write "Im git-status als deleted markiert — entweder absichtlich loeschen und"
write "committen, oder Datei wiederherstellen."
write ""

git -C "$REPO_ROOT" ls-files --deleted 2>/dev/null | while IFS= read -r f; do
    [[ -z "$f" ]] && continue
    write "- $f"
done

write ""

# --- 5. Bekannte verwaiste Stellen aus ADR-Folge ---
write "## Bekannte verwaiste Stellen (manuell kuratiert)"
write ""
write "Aus den ADR-018/019/020-Migrationen und der heutigen Aufraeum-Sorge:"
write ""

KNOWN_ORPHANS=(
    "$REPO_ROOT/volumes/knowledge-base"
    "$REPO_ROOT/scripts/system/generate-session-summary.py"
    "$REPO_ROOT/scripts/system/export-sessions-to-knowledge.py"
    "$REPO_ROOT/docker/migrate_roadmap_to_baserow.py"
    "$REPO_ROOT/learning-lab"
    "$REPO_ROOT/apps/knowledge-api"
)

for p in "${KNOWN_ORPHANS[@]}"; do
    if [[ -e "$p" ]]; then
        write "- $(describe_path "$p")"
    fi
done

write ""
write "---"
write ""
write "Naechster Schritt: pro Eintrag entscheiden und ggf. mit"
write "\`scripts/archive/archive-to.sh <path> <topic-slug> [reason]\` archivieren."

[[ -n "$OUTPUT_FILE" ]] && echo "audit written to: $OUTPUT_FILE"
