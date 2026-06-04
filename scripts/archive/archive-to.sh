#!/bin/bash
# archive-to — verschiebt einen Pfad ins zentrale /opt/mora02/_archive/
# Konvention per ADR-021. Anstatt zu loeschen: ab damit ins Archive.
#
# Aufruf:
#   archive-to.sh <source-path> <topic-slug> [reason words...]
#
# Beispiel:
#   archive-to.sh apps/knowledge-api knowledge-api "aufgeloest per ADR-020"
#
# Ergebnis:
#   /opt/mora02/_archive/2606041500_knowledge-api/
#     ├── _MANIFEST.md
#     └── apps/knowledge-api/   <-- Original-Pfad-Struktur erhalten
#
# Rollback (aus dem Manifest heraus):
#   cp -r /opt/mora02/_archive/2606041500_knowledge-api/apps/knowledge-api /opt/mora02/apps/

set -e

REPO_ROOT="/opt/mora02"
ARCHIVE_ROOT="${REPO_ROOT}/_archive"

usage() {
    echo "Usage: $0 <source-path> <topic-slug> [reason...]" >&2
    echo "       source-path:  absolute or relative to ${REPO_ROOT}" >&2
    echo "       topic-slug:   kebab-case, e.g. knowledge-api" >&2
    echo "       reason:       free-text begruendung (in das Manifest)" >&2
    exit 1
}

[[ $# -lt 2 ]] && usage

SOURCE_ARG="$1"
TOPIC_SLUG="$2"
shift 2
REASON="$*"

# Validate topic-slug (kebab-case-ish)
if [[ ! "$TOPIC_SLUG" =~ ^[a-z0-9][a-z0-9_-]*$ ]]; then
    echo "error: topic-slug muss kebab-case sein (lowercase, hyphens), nicht '$TOPIC_SLUG'" >&2
    exit 1
fi

# Resolve source to an absolute path inside the repo
if [[ "$SOURCE_ARG" = /* ]]; then
    SOURCE_ABS="$SOURCE_ARG"
else
    SOURCE_ABS="${REPO_ROOT}/${SOURCE_ARG}"
fi

if [[ ! -e "$SOURCE_ABS" ]]; then
    echo "error: source-path existiert nicht: $SOURCE_ABS" >&2
    exit 1
fi

# Refuse to archive paths outside the repo or the archive itself
if [[ "$SOURCE_ABS" != "${REPO_ROOT}/"* ]]; then
    echo "error: source liegt nicht unter ${REPO_ROOT}" >&2
    exit 1
fi
if [[ "$SOURCE_ABS" = "${ARCHIVE_ROOT}"* ]]; then
    echo "error: source liegt schon im Archive" >&2
    exit 1
fi

# Compute the path relative to the repo root, so the structure is preserved
REL_PATH="${SOURCE_ABS#${REPO_ROOT}/}"

# Timestamp slug
TS=$(date +%y%m%d%H%M)
ARCHIVE_DIR="${ARCHIVE_ROOT}/${TS}_${TOPIC_SLUG}"

if [[ -e "$ARCHIVE_DIR" ]]; then
    echo "error: archive-dir existiert bereits: $ARCHIVE_DIR" >&2
    echo "       (gleicher topic-slug in derselben Minute? warte kurz oder waehle anderen slug)" >&2
    exit 1
fi

# Git HEAD hash, if we are in a git checkout
GIT_HEAD=$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || echo "(no git)")

# Build target path mirroring the source structure
TARGET_PATH="${ARCHIVE_DIR}/${REL_PATH}"
TARGET_PARENT=$(dirname "$TARGET_PATH")

mkdir -p "$TARGET_PARENT"
mv "$SOURCE_ABS" "$TARGET_PATH"

# Write the manifest
MANIFEST="${ARCHIVE_DIR}/_MANIFEST.md"
{
    echo "# Archive Manifest — ${TS}_${TOPIC_SLUG}"
    echo
    echo "**Topic:** ${TOPIC_SLUG}"
    echo "**Archived at:** $(date -Iseconds)"
    echo "**git HEAD at archive time:** ${GIT_HEAD}"
    echo
    echo "## Original path"
    echo "\`\`\`"
    echo "${SOURCE_ABS}"
    echo "\`\`\`"
    echo
    echo "## Reason"
    if [[ -n "$REASON" ]]; then
        echo "$REASON"
    else
        echo "(no reason given)"
    fi
    echo
    echo "## Rollback"
    echo "\`\`\`bash"
    echo "cp -r '${TARGET_PATH}' '${SOURCE_ABS}'"
    echo "\`\`\`"
} > "$MANIFEST"

echo "archived:  $SOURCE_ABS"
echo "       to: $TARGET_PATH"
echo "manifest:  $MANIFEST"
echo
echo "rollback:"
echo "  cp -r '${TARGET_PATH}' '${SOURCE_ABS}'"
