#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# MORA02 PILOT — UI Lint & Audit Script v2.2
# Run after every session to catch structural issues early.
# Usage: bash pilot-lint.sh [path-to-ui-dir]
# ═══════════════════════════════════════════════════════════════

UI_DIR="${1:-/opt/mora02/apps/pilot/ui}"
ERRORS=0
WARNINGS=0

R='\033[0;31m'
Y='\033[0;33m'
G='\033[0;32m'
C='\033[0;36m'
N='\033[0m'

header() { echo -e "\n${C}═══ $1 ═══${N}"; }
err()    { echo -e "  ${R}✗ $1${N}"; ((ERRORS++)); }
warn()   { echo -e "  ${Y}⚠ $1${N}"; ((WARNINGS++)); }
ok()     { echo -e "  ${G}✓ $1${N}"; }
info()   { echo -e "  ${C}ℹ $1${N}"; }

echo -e "${C}MORA02 PILOT — UI Audit v2.2${N}"
echo "Directory: $UI_DIR"
echo "Date: $(date '+%Y-%m-%d %H:%M')"

if [ ! -d "$UI_DIR" ]; then
    echo -e "${R}ERROR: $UI_DIR not found${N}"
    exit 1
fi

CSS_FILES=$(find "$UI_DIR/css" -name "*.css" 2>/dev/null)
HTML_FILES=$(find "$UI_DIR" -name "*.html" 2>/dev/null)
JS_FILES=$(find "$UI_DIR/js" -name "*.js" 2>/dev/null)
SPRITE="$UI_DIR/icons/sprite.svg"

# ─── 1. SPRITE ICON INTEGRITY ────────────────────────────────
header "1. Sprite Icon References"

if [ -f "$SPRITE" ]; then
    DEFINED=$(grep -o 'id="i-[^"]*"' "$SPRITE" | sed 's/id="//;s/"//' | sort)
    REFERENCED=$(grep -roh 'href="[^"]*sprite\.svg#[^"]*"' $HTML_FILES $JS_FILES 2>/dev/null \
        | sed 's/.*#//;s/"//' | sort -u)

    MISSING_ICONS=0
    for icon in $REFERENCED; do
        if ! echo "$DEFINED" | grep -qx "$icon"; then
            err "Referenced but not in sprite: $icon"
            MISSING_ICONS=1
        fi
    done
    for icon in $DEFINED; do
        if ! echo "$REFERENCED" | grep -qx "$icon"; then
            warn "Defined in sprite but unused: $icon"
        fi
    done
    [ $MISSING_ICONS -eq 0 ] && ok "All referenced icons exist in sprite"
else
    err "Sprite file not found: $SPRITE"
fi

# ─── 2. CSS CLASS CROSS-CHECK ────────────────────────────────
header "2. CSS ↔ HTML Class Cross-Check"

CSS_CLASSES=$(grep -oh '\.[a-z][a-zA-Z0-9_-]*' $CSS_FILES 2>/dev/null \
    | sed 's/^\.//' | sort -u)

HTML_CLASSES=$(grep -oh 'class="[^"]*"' $HTML_FILES 2>/dev/null \
    | sed 's/class="//;s/"//' | tr ' ' '\n' | grep -v '^$' | sort -u)

JS_CLASSES=$(grep -oh "classList\.\(add\|toggle\|replace\|remove\)('[^']*'" $JS_FILES 2>/dev/null \
    | sed "s/classList\.\(add\|toggle\|replace\|remove\)('//;s/'$//" | sort -u)
JS_CLASSES2=$(grep -oh 'classList\.\(add\|toggle\|replace\|remove\)("[^"]*"' $JS_FILES 2>/dev/null \
    | sed 's/classList\.\(add\|toggle\|replace\|remove\)("//;s/"$//' | sort -u)

ALL_USED_CLASSES=$(echo -e "$HTML_CLASSES\n$JS_CLASSES\n$JS_CLASSES2" | sort -u)
DYNAMIC_PREFIXES="hljs-"

ORPHAN_COUNT=0
for cls in $CSS_CLASSES; do
    [[ "$cls" == *":"* ]] && continue
    [[ "$cls" == "woff2" ]] && continue
    SKIP=0
    for prefix in $DYNAMIC_PREFIXES; do
        [[ "$cls" == ${prefix}* ]] && SKIP=1 && break
    done
    [ $SKIP -eq 1 ] && continue
    if ! echo "$ALL_USED_CLASSES" | grep -qx "$cls"; then
        if ! grep -rq "$cls" $JS_FILES 2>/dev/null; then
            warn "CSS class defined but not found in HTML/JS: .$cls"
            ((ORPHAN_COUNT++))
        fi
    fi
done
[ $ORPHAN_COUNT -eq 0 ] && ok "All CSS classes are referenced in HTML/JS"
info "Skipped: hljs-* (syntax highlighting, added dynamically)"

MISSING_COUNT=0
for cls in $ALL_USED_CLASSES; do
    [ -z "$cls" ] && continue
    if ! echo "$CSS_CLASSES" | grep -qx "$cls"; then
        [[ "$cls" == hljs* ]] && continue
        err "HTML/JS uses class not defined in CSS: .$cls"
        ((MISSING_COUNT++))
    fi
done
[ $MISSING_COUNT -eq 0 ] && ok "All HTML/JS classes are defined in CSS"

# ─── 3. HARDCODED VALUES ─────────────────────────────────────
header "3. Hardcoded Values (should be design tokens)"

for cssfile in $CSS_FILES; do
    fname=$(basename "$cssfile")
    [ "$fname" = "design-tokens.css" ] && continue

    HEX=$(grep -n '#[0-9a-fA-F]\{3,8\}' "$cssfile" | grep -v 'var(' | grep -v '^\s*/[/*]')
    if [ -n "$HEX" ]; then
        while IFS= read -r line; do
            warn "$fname: hardcoded color → $line"
        done <<< "$HEX"
    fi

    RGB=$(grep -n 'rgb[a]\?(' "$cssfile" | grep -v 'var(' | grep -v '^\s*/[/*]')
    if [ -n "$RGB" ]; then
        while IFS= read -r line; do
            warn "$fname: hardcoded rgb → $line"
        done <<< "$RGB"
    fi

    PX=$(grep -n '[^0-1][0-9]\+px' "$cssfile" \
        | grep -v 'var(' \
        | grep -v '^\s*/[/*]' \
        | grep -v '@font-face' \
        | grep -v '@media')
    if [ -n "$PX" ]; then
        while IFS= read -r line; do
            warn "$fname: hardcoded px → $line"
        done <<< "$PX"
    fi
done

ok "design-tokens.css skipped (source of truth)"
info "Skipped: @media breakpoints (hardcoded px is standard practice)"

# ─── 4. DUPLICATE SELECTORS (media-query-aware, mawk-safe) ───
header "4. Duplicate CSS Selectors (context-aware)"

SELECTOR_LIST=$(for f in $CSS_FILES; do
    awk '
    BEGIN { depth=0; context="root" }
    {
        line = $0
        if (line ~ /^@media/) {
            tmp = line
            gsub(/\{.*/, "", tmp)
            gsub(/^[[:space:]]+/, "", tmp)
            gsub(/[[:space:]]+$/, "", tmp)
            context = tmp
        }

        tmp = line; opens = gsub(/\{/, "{", tmp)
        tmp = line; closes = gsub(/\}/, "}", tmp)
        depth = depth + opens - closes
        if (depth < 0) depth = 0
        if (depth == 0 && closes > 0) context = "root"

        if (line ~ /\{/ && line !~ /^@/ && line !~ /^[[:space:]]*\//) {
            sel = line
            gsub(/\{.*/, "", sel)
            gsub(/^[[:space:]]+/, "", sel)
            gsub(/[[:space:]]+$/, "", sel)
            if (sel != "" && sel !~ /^from$/ && sel !~ /^to$/ && sel !~ /^[0-9]+%/) {
                print FILENAME "|" context "|" sel
            }
        }
    }
    ' "$f"
done)

# Display duplicates
echo "$SELECTOR_LIST" | awk -F'|' '
{
    key = $2 "|" $3
    if (!(key in files)) {
        files[key] = $1
    } else {
        files[key] = files[key] "," $1
    }
    count[key]++
}
END {
    for (key in count) {
        if (count[key] > 1) {
            idx = index(key, "|")
            ctx = substr(key, 1, idx-1)
            sel = substr(key, idx+1)
            n = split(files[key], f, ",")
            seen = ""
            for (i=1; i<=n; i++) {
                sub(/.*\//, "", f[i])
                if (seen !~ f[i]) {
                    if (seen != "") seen = seen ", "
                    seen = seen f[i]
                }
            }
            if (ctx == "root") {
                printf "ERROR|%s|%s|%d\n", sel, seen, count[key]
            } else {
                printf "WARN|%s|%s (%s)|%d\n", sel, seen, ctx, count[key]
            }
        }
    }
}' | sort | while IFS='|' read -r level sel location times; do
    if [ "$level" = "ERROR" ]; then
        echo -e "  ${R}✗ Duplicate selector '$sel' (${times}x) in: $location${N}"
    else
        echo -e "  ${Y}⚠ Duplicate selector '$sel' (${times}x) in: $location${N}"
    fi
done

# Count duplicates OUTSIDE subshell and add to counters
ROOT_DUPES=$(echo "$SELECTOR_LIST" | awk -F'|' '
{ key = $2 "|" $3; count[key]++ }
END {
    d = 0
    for (key in count) {
        if (count[key] > 1) {
            idx = index(key, "|")
            ctx = substr(key, 1, idx-1)
            if (ctx == "root") d++
        }
    }
    print d
}')
ERRORS=$((ERRORS + ROOT_DUPES))

MEDIA_DUPES=$(echo "$SELECTOR_LIST" | awk -F'|' '
{ key = $2 "|" $3; count[key]++ }
END {
    d = 0
    for (key in count) {
        if (count[key] > 1) {
            idx = index(key, "|")
            ctx = substr(key, 1, idx-1)
            if (ctx != "root") d++
        }
    }
    print d
}')
WARNINGS=$((WARNINGS + MEDIA_DUPES))

[ "$ROOT_DUPES" -eq 0 ] && ok "No duplicate selectors in root context"
[ "$MEDIA_DUPES" -gt 0 ] && info "$MEDIA_DUPES duplicates inside @media — check if intentional (override vs mistake)"

# ─── 5. NAMING CONVENTION ────────────────────────────────────
header "5. Naming Convention (kebab-case)"

BAD_NAMES=$(echo "$CSS_CLASSES" | grep -E '[A-Z]|_' | grep -v '^hljs-')
if [ -n "$BAD_NAMES" ]; then
    while IFS= read -r name; do
        [[ "$name" == hljs* ]] && continue
        warn "Non-kebab-case class: .$name"
    done <<< "$BAD_NAMES"
else
    ok "All CSS classes use kebab-case"
fi

# ─── 6. FILE STRUCTURE SANITY ────────────────────────────────
header "6. File Structure"

REQUIRED_FILES=(
    "index.html"
    "css/design-tokens.css"
    "css/pilot.css"
    "css/chat.css"
    "icons/sprite.svg"
    "js/app.js"
)
for f in "${REQUIRED_FILES[@]}"; do
    if [ -f "$UI_DIR/$f" ]; then
        ok "$f exists"
    else
        err "Missing required file: $f"
    fi
done

STRAY=$(find "$UI_DIR" -maxdepth 1 -type f ! -name "index.html" ! -name "*.md" ! -name ".gitkeep")
if [ -n "$STRAY" ]; then
    while IFS= read -r f; do
        warn "File in UI root (should be in subfolder): $(basename $f)"
    done <<< "$STRAY"
fi

# ─── 7. HTML VALIDITY QUICK-CHECK ────────────────────────────
header "7. HTML Quick-Check"

for htmlfile in $HTML_FILES; do
    fname=$(basename "$htmlfile")
    for tag in div section nav main header footer; do
        OPEN=$(grep -o "<${tag}[ >]" "$htmlfile" | wc -l)
        CLOSE=$(grep -o "</${tag}>" "$htmlfile" | wc -l)
        if [ "$OPEN" -ne "$CLOSE" ]; then
            DIFF=$((CLOSE - OPEN))
            if [ $DIFF -gt 0 ]; then
                err "$fname: <$tag> opened $OPEN x but closed $CLOSE x → $DIFF extra closing tag(s)"
            else
                DIFF=$((-DIFF))
                err "$fname: <$tag> opened $OPEN x but closed $CLOSE x → $DIFF unclosed tag(s)"
            fi
        fi
    done
    EMPTY_CLASS=$(grep -c 'class=""' "$htmlfile")
    if [ "$EMPTY_CLASS" -gt 0 ]; then
        warn "$fname: $EMPTY_CLASS empty class=\"\" attributes"
    fi
done
ok "Basic tag balance checked"

# ─── 8. CSS var() COVERAGE ───────────────────────────────────
header "8. Design Token Coverage"

for cssfile in $CSS_FILES; do
    fname=$(basename "$cssfile")
    [ "$fname" = "design-tokens.css" ] && continue
    TOTAL_PROPS=$(grep -c ':' "$cssfile" 2>/dev/null || echo 0)
    VAR_PROPS=$(grep -c 'var(--' "$cssfile" 2>/dev/null || echo 0)
    if [ "$TOTAL_PROPS" -gt 0 ]; then
        PCT=$((VAR_PROPS * 100 / TOTAL_PROPS))
        if [ $PCT -ge 80 ]; then
            ok "$fname: ${PCT}% token coverage ($VAR_PROPS/$TOTAL_PROPS properties)"
        elif [ $PCT -ge 50 ]; then
            warn "$fname: ${PCT}% token coverage ($VAR_PROPS/$TOTAL_PROPS) — target >80%"
        else
            err "$fname: ${PCT}% token coverage ($VAR_PROPS/$TOTAL_PROPS) — too many hardcoded values"
        fi
    fi
done

# ─── SUMMARY ─────────────────────────────────────────────────
header "SUMMARY"
echo -e "  ${R}Errors:   $ERRORS${N}"
echo -e "  ${Y}Warnings: $WARNINGS${N}"

if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo -e "\n  ${G}✓ CLEAN — No issues found${N}\n"
elif [ $ERRORS -eq 0 ]; then
    echo -e "\n  ${Y}⚠ ACCEPTABLE — Warnings only, review when convenient${N}\n"
else
    echo -e "\n  ${R}✗ FIX NEEDED — Errors should be resolved before next session${N}\n"
fi

exit $ERRORS
