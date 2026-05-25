#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# MORA02 PILOT — Code Lint & Audit Script v3.0
# Run after every session to catch structural issues early.
#
# Usage: bash pilot-lint.sh [ui-dir] [apps-dir] [scripts-dir]
#
# Checks 1-8:   HTML / CSS / Frontend (from v2.2)
# Checks 9-22:  JS / Python / Shell / Cross-cutting (NEW)
# ═══════════════════════════════════════════════════════════════

UI_DIR="${1:-/opt/mora02/apps/pilot/ui}"
APPS_DIR="${2:-/opt/mora02/apps}"
SCRIPTS_DIR="${3:-/opt/mora02/scripts}"

ERRORS=0
WARNINGS=0
INFOS=0

# Colors
R='\033[0;31m'
Y='\033[0;33m'
G='\033[0;32m'
C='\033[0;36m'
N='\033[0m'

# Safe grep -c: always returns a number (0 if no match or file unreadable)
gcount() { local n; n=$(grep -c "$@" 2>/dev/null) || true; echo "${n:-0}"; }

header() { echo -e "\n${C}═══ $1 ═══${N}"; }
err()    { echo -e "  ${R}✗ $1${N}"; ERRORS=$((ERRORS + 1)); }
warn()   { echo -e "  ${Y}⚠ $1${N}"; WARNINGS=$((WARNINGS + 1)); }
ok()     { echo -e "  ${G}✓ $1${N}"; }
info()   { echo -e "  ${C}ℹ $1${N}"; INFOS=$((INFOS + 1)); }

echo -e "${C}MORA02 PILOT — Code Audit v3.0${N}"
echo "UI Dir:      $UI_DIR"
echo "Apps Dir:    $APPS_DIR"
echo "Scripts Dir: $SCRIPTS_DIR"
echo "Date:        $(date '+%Y-%m-%d %H:%M')"

# ─── PRE-CHECK ────────────────────────────────────────────────
if [ ! -d "$UI_DIR" ]; then
    echo -e "${R}ERROR: UI directory $UI_DIR not found${N}"
    exit 1
fi

CSS_FILES=$(find "$UI_DIR" -name "*.css" -not -path "*/node_modules/*" 2>/dev/null)
HTML_FILES=$(find "$UI_DIR" -name "*.html" -not -path "*/node_modules/*" 2>/dev/null)
JS_FILES=$(find "$UI_DIR" -name "*.js" -not -name "*.min.js" -not -path "*/node_modules/*" 2>/dev/null)
PY_FILES=$(find "$APPS_DIR" -name "*.py" -not -path "*/__pycache__/*" -not -path "*/node_modules/*" -not -path "*/.venv/*" -not -path "*/_archive/*" 2>/dev/null)
SH_FILES=$(find "$SCRIPTS_DIR" -name "*.sh" 2>/dev/null)
SPRITE="$UI_DIR/icons/sprite.svg"

# Also scan docker script-runner app dir if it exists
SCRIPTRUNNER_DIR="/opt/mora02/docker/script-runner/app"
if [ -d "$SCRIPTRUNNER_DIR" ]; then
    PY_FILES="$PY_FILES
$(find "$SCRIPTRUNNER_DIR" -name "*.py" -not -path "*/__pycache__/*" 2>/dev/null)"
fi

# ═══════════════════════════════════════════════════════════════
# SECTION A: HTML / CSS / FRONTEND (Checks 1-8, from v2.2)
# ═══════════════════════════════════════════════════════════════

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
header "2. CSS ↔ HTML/JS Class Cross-Check"

CSS_CLASSES=$(grep -oh '\.[a-zA-Z][a-zA-Z0-9_-]*' $CSS_FILES 2>/dev/null \
    | sed 's/^\.//' | sort -u | grep -v '^hljs-')

HTML_CLASSES=$(grep -oh 'class="[^"]*"' $HTML_FILES 2>/dev/null \
    | sed 's/class="//;s/"//' | tr ' ' '\n' \
    | grep -E '^[a-z][a-z0-9-]*$' | sort -u)

JS_CLASSES_CL=$(grep -oh "classList\.\(add\|toggle\|remove\|replace\|contains\)(['\"][^'\"]*['\"]" $JS_FILES 2>/dev/null \
    | sed "s/.*['\"]//;s/['\"].*//" | sort -u)

# Also extract classes from innerHTML string literals: class="word word" (only clean alphanumeric-hyphen classes)
JS_CLASSES_STR=$(grep -oh 'class="[^"]*"' $JS_FILES 2>/dev/null \
    | sed 's/class="//;s/"//' | tr ' ' '\n' \
    | grep -E '^[a-z][a-z0-9-]*$' | sort -u)

# Also extract from className assignments: className = 'foo bar'
JS_CLASSES_CN=$(grep -oh "className\s*=\s*['\"][^'\"]*['\"]" $JS_FILES 2>/dev/null \
    | sed "s/className\s*=\s*['\"]//;s/['\"]$//" | tr ' ' '\n' | sort -u)

# Broad sweep: hyphenated words in single-quoted JS strings (class-name pattern)
JS_CLASSES_BROAD=$(grep -oh "'[a-z][a-z0-9-]*'" $JS_FILES 2>/dev/null \
    | tr -d "'" | grep -E '^[a-z][a-z0-9]+-[a-z]' | sort -u)

JS_CLASSES=$(printf '%s\n%s\n%s\n%s' "$JS_CLASSES_CL" "$JS_CLASSES_STR" "$JS_CLASSES_CN" "$JS_CLASSES_BROAD" | sort -u)

ALL_USED=$(printf '%s\n%s' "$HTML_CLASSES" "$JS_CLASSES" | sort -u)

# Known dynamic classes: animation utilities, JS state toggles, font-face artifacts, short generics
DYNAMIC_SKIP="a-d1|a-d2|a-d3|a-d4|a-d5|a-d6|a-d7|a-d8|a-fade|a-fade-slow|a-up|a-up-slow|a-down|a-left|a-right|a-scale"
DYNAMIC_SKIP="$DYNAMIC_SKIP|fb-open|mob-open|dragging|drag-over|dragover|collapsed|switching|pulse|visible|on|fl-disabled|cmd-active"
DYNAMIC_SKIP="$DYNAMIC_SKIP|bucket-dragging|bucket-drop-active|bucket-drop-reject|bucket-add-ok"
DYNAMIC_SKIP="$DYNAMIC_SKIP|css|js|org|w3|woff2"
# Short/generic class names that regex-based extraction misses in innerHTML strings
DYNAMIC_SKIP="$DYNAMIC_SKIP|card|cards|img-preview|img-revision|img-variants|post-item-active|wiki-doc"

UNUSED_CSS=0
UNUSED_CSS_COUNT=0
for cls in $CSS_CLASSES; do
    if echo "$cls" | grep -qE "^($DYNAMIC_SKIP)$"; then continue; fi
    if ! echo "$ALL_USED" | grep -qx "$cls"; then
        UNUSED_CSS_COUNT=$((UNUSED_CSS_COUNT + 1))
        UNUSED_CSS=1
    fi
done
if [ $UNUSED_CSS -eq 0 ]; then
    ok "All CSS classes are referenced in HTML/JS"
else
    info "$UNUSED_CSS_COUNT CSS classes defined but not found in HTML/JS (may be dead code — run with -v for list)"
fi
info "Skipped: hljs-*, animation utilities, JS state classes (added dynamically)"

# For "used but not defined" check: only use high-confidence sources (HTML attrs + classList calls)
ALL_USED_STRICT=$(printf '%s\n%s' "$HTML_CLASSES" "$JS_CLASSES_CL" | sort -u)

MISSING_CSS=0
for cls in $ALL_USED_STRICT; do
    [ -z "$cls" ] && continue
    # Skip dynamically-generated classes (syntax highlighting, TTS engine toggles)
    case "$cls" in hljs-*|tts-*) continue ;; esac
    if ! echo "$CSS_CLASSES" | grep -qx "$cls"; then
        err "HTML/JS uses class not defined in CSS: .$cls"
        MISSING_CSS=1
    fi
done
[ $MISSING_CSS -eq 0 ] && ok "All HTML/JS classes are defined in CSS"

# ─── 3. HARDCODED CSS VALUES ─────────────────────────────────
header "3. Hardcoded CSS Values (should be design tokens)"

for cssfile in $CSS_FILES; do
    fname=$(basename "$cssfile")
    [ "$fname" = "design-tokens.css" ] && continue

    # Find hardcoded hex/rgb but skip @media lines
    HARDCODED=$(grep -n '#[0-9a-fA-F]\{3,8\}\b\|rgb(' "$cssfile" 2>/dev/null \
        | grep -v '@media\|var(--\|\/\*\|hljs')
    if [ -n "$HARDCODED" ]; then
        echo "$HARDCODED" | while read -r line; do
            warn "$fname: hardcoded color → $line"
        done
    fi

    # Hardcoded px outside @media
    PX_LINES=$(grep -n '[0-9]\+px' "$cssfile" 2>/dev/null \
        | grep -v '@media\|var(--\|\/\*\|border-radius\|outline-offset')
    if [ -n "$PX_LINES" ]; then
        echo "$PX_LINES" | head -3 | while read -r line; do
            warn "$fname: hardcoded px → $line"
        done
    fi
done
ok "design-tokens.css skipped (source of truth)"
info "Skipped: @media breakpoints (hardcoded px is standard practice)"

# ─── 4. DUPLICATE CSS SELECTORS ──────────────────────────────
header "4. Duplicate CSS Selectors (context-aware)"

for cssfile in $CSS_FILES; do
    fname=$(basename "$cssfile")
    [ "$fname" = "design-tokens.css" ] && continue

    # Track selectors with their context (media query or root)
    DUPES=$(awk '
    BEGIN { context = "root" }
    /@media/ { context = $0; gsub(/[[:space:]]+/, " ", context) }
    /^}/ && context != "root" { context = "root" }
    /^[.#a-zA-Z]/ && !/^\// {
        sel = $0
        gsub(/[[:space:]]*\{.*/, "", sel)
        gsub(/[[:space:]]+$/, "", sel)
        key = context "|" sel
        count[key]++
        if (count[key] == 2) print sel " (2x)"
    }
    ' "$cssfile" 2>/dev/null)

    if [ -n "$DUPES" ]; then
        echo "$DUPES" | while read -r line; do
            err "Duplicate selector '$line' in: $fname"
        done
    fi
done
if [ $ERRORS -eq 0 ] || true; then
    # Only show if no dupes found above
    DUP_CHECK=$(awk '
    BEGIN { c = 0 }
    /@media/ { ctx = $0 }
    /^}/ && ctx != "" { ctx = "" }
    /^[.#a-zA-Z]/ && !/^\// {
        sel = $0; gsub(/[[:space:]]*\{.*/, "", sel)
        key = ctx "|" sel; cnt[key]++
        if (cnt[key] == 2) c++
    }
    END { print c }
    ' $CSS_FILES 2>/dev/null)
    [ "$DUP_CHECK" = "0" ] && ok "No duplicate selectors in root context"
fi

# ─── 5. NAMING CONVENTION ────────────────────────────────────
header "5. Naming Convention (kebab-case)"

BAD_NAMES=$(grep -oh '\.[a-zA-Z][a-zA-Z0-9_-]*' $CSS_FILES 2>/dev/null \
    | sed 's/^\.//' | sort -u \
    | grep '[A-Z]\|_' | grep -v '^hljs-\|^js-')

if [ -n "$BAD_NAMES" ]; then
    echo "$BAD_NAMES" | while read -r cls; do
        err "Non-kebab-case class: .$cls"
    done
else
    ok "All CSS classes use kebab-case"
fi

# ─── 6. FILE STRUCTURE ───────────────────────────────────────
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
        err "$f MISSING"
    fi
done

# ─── 7. HTML TAG BALANCE ─────────────────────────────────────
header "7. HTML Quick-Check"

for htmlfile in $HTML_FILES; do
    fname=$(basename "$htmlfile")
    for tag in div section main nav header footer aside article; do
        OPEN=$(grep -o "<${tag}[ >]" "$htmlfile" 2>/dev/null | wc -l)
        CLOSE=$(grep -o "</${tag}>" "$htmlfile" 2>/dev/null | wc -l)
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
done
ok "Basic tag balance checked"

# ─── 8. DESIGN TOKEN COVERAGE ────────────────────────────────
header "8. Design Token Coverage"

for cssfile in $CSS_FILES; do
    fname=$(basename "$cssfile")
    [ "$fname" = "design-tokens.css" ] && continue

    TOTAL_PROPS=$(gcount ':' "$cssfile")
    VAR_PROPS=$(gcount 'var(--' "$cssfile")

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

# ═══════════════════════════════════════════════════════════════
# SECTION B: JAVASCRIPT (Checks 9-13)
# ═══════════════════════════════════════════════════════════════

# ─── 9. JS SYNTAX CHECK ──────────────────────────────────────
header "9. JS Syntax Check"

if command -v node >/dev/null 2>&1; then
    JS_SYNTAX_OK=0
    JS_SYNTAX_FAIL=0
    for jsfile in $JS_FILES; do
        fname=$(basename "$jsfile")
        if node --check "$jsfile" 2>/dev/null; then
            JS_SYNTAX_OK=$((JS_SYNTAX_OK + 1))
        else
            err "Syntax error in: $fname"
            JS_SYNTAX_FAIL=$((JS_SYNTAX_FAIL + 1))
        fi
    done
    [ $JS_SYNTAX_FAIL -eq 0 ] && ok "All $JS_SYNTAX_OK JS files pass syntax check"
else
    warn "node not installed — skipping JS syntax check"
fi

# ─── 10. JS DEBUG LEICHEN ────────────────────────────────────
header "10. JS Debug Statements"

# Whitelist file for intentional console.log (one path per line)
CONSOLE_WHITELIST="/opt/mora02/scripts/.lint-console-whitelist"

for jsfile in $JS_FILES; do
    fname=$(basename "$jsfile")

    # Skip whitelisted files
    if [ -f "$CONSOLE_WHITELIST" ] && grep -qx "$jsfile" "$CONSOLE_WHITELIST" 2>/dev/null; then
        continue
    fi

    COUNT=$(gcount 'console\.log\b' "$jsfile")
    if [ "$COUNT" -gt 0 ]; then
        warn "$fname: $COUNT console.log statement(s) — remove before production"
    fi

    # Also check console.warn/error used as debug (not necessarily bad, just track)
    WARN_COUNT=$(gcount 'console\.warn\b\|console\.error\b' "$jsfile")
    if [ "$WARN_COUNT" -gt 5 ]; then
        info "$fname: $WARN_COUNT console.warn/error — review if all needed"
    fi
done

TOTAL_LOGS=$(grep -r 'console\.log\b' $JS_FILES 2>/dev/null | wc -l)
[ "$TOTAL_LOGS" -eq 0 ] && ok "No console.log found in JS files"

# ─── 11. FETCH WITHOUT ERROR HANDLING ────────────────────────
header "11. fetch() Error Handling"

for jsfile in $JS_FILES; do
    fname=$(basename "$jsfile")

    # Find fetch() calls and check surrounding context for .catch or try
    # Strategy: find line numbers with fetch(, check if .catch or try/catch nearby
    FETCH_LINES=$(grep -n 'fetch(' "$jsfile" 2>/dev/null | grep -v '\/\/' | grep -v '\.catch')

    if [ -n "$FETCH_LINES" ]; then
        echo "$FETCH_LINES" | while read -r fetchline; do
            LINENO=$(echo "$fetchline" | cut -d: -f1)

            # Check 5 lines before for try { and 10 lines after for .catch
            START=$((LINENO > 5 ? LINENO - 5 : 1))
            END=$((LINENO + 10))

            CONTEXT=$(sed -n "${START},${END}p" "$jsfile" 2>/dev/null)
            HAS_TRY=$(echo "$CONTEXT" | grep -c 'try\s*{')
            HAS_CATCH=$(echo "$CONTEXT" | grep -c '\.catch\|catch\s*(')

            if [ "$HAS_TRY" -eq 0 ] && [ "$HAS_CATCH" -eq 0 ]; then
                warn "$fname:$LINENO fetch() without try/catch or .catch()"
            fi
        done
    fi
done

TOTAL_UNHANDLED=$(for jsfile in $JS_FILES; do
    grep -n 'fetch(' "$jsfile" 2>/dev/null | grep -v '\/\/' | grep -v '\.catch' | while read -r fetchline; do
        LINENO=$(echo "$fetchline" | cut -d: -f1)
        START=$((LINENO > 5 ? LINENO - 5 : 1))
        END=$((LINENO + 10))
        CONTEXT=$(sed -n "${START},${END}p" "$jsfile" 2>/dev/null)
        HAS_TRY=$(echo "$CONTEXT" | grep -c 'try\s*{')
        HAS_CATCH=$(echo "$CONTEXT" | grep -c '\.catch\|catch\s*(')
        [ "$HAS_TRY" -eq 0 ] && [ "$HAS_CATCH" -eq 0 ] && echo "1"
    done
done | wc -l)
[ "$TOTAL_UNHANDLED" -eq 0 ] && ok "All fetch() calls have error handling"

# ─── 12. JS MIXED QUOTES ─────────────────────────────────────
header "12. JS Quote Consistency"

for jsfile in $JS_FILES; do
    fname=$(basename "$jsfile")

    SINGLE=$(grep -o "'" "$jsfile" 2>/dev/null | wc -l)
    DOUBLE=$(grep -o '"' "$jsfile" 2>/dev/null | wc -l)

    # Skip if file is tiny
    TOTAL=$((SINGLE + DOUBLE))
    [ "$TOTAL" -lt 20 ] && continue

    if [ "$SINGLE" -gt 0 ] && [ "$DOUBLE" -gt 0 ]; then
        # Calculate ratio — flag if close to 50/50
        if [ "$TOTAL" -gt 0 ]; then
            RATIO=$((SINGLE * 100 / TOTAL))
            if [ "$RATIO" -gt 30 ] && [ "$RATIO" -lt 70 ]; then
                info "$fname: mixed quotes (${RATIO}% single, $((100 - RATIO))% double) — pick one style"
            fi
        fi
    fi
done

# ─── 13. JS GLOBAL VARIABLES ─────────────────────────────────
header "13. JS Global var Declarations"

for jsfile in $JS_FILES; do
    fname=$(basename "$jsfile")

    # Find 'var ' at start of line (top-level scope indicator)
    GLOBAL_VARS=$(grep -n '^var \|^  var ' "$jsfile" 2>/dev/null | head -5)
    if [ -n "$GLOBAL_VARS" ]; then
        COUNT=$(echo "$GLOBAL_VARS" | wc -l)
        warn "$fname: $COUNT top-level var declaration(s) — consider let/const"
    fi
done

# ═══════════════════════════════════════════════════════════════
# SECTION C: PYTHON (Checks 14-16)
# ═══════════════════════════════════════════════════════════════

# ─── 14. PYTHON SYNTAX CHECK ─────────────────────────────────
header "14. Python Syntax Check"

if command -v python3 >/dev/null 2>&1; then
    PY_SYNTAX_OK=0
    PY_SYNTAX_FAIL=0
    for pyfile in $PY_FILES; do
        [ -z "$pyfile" ] && continue
        fname=$(basename "$pyfile")
        if python3 -c "import ast; ast.parse(open('$pyfile').read())" 2>/dev/null; then
            PY_SYNTAX_OK=$((PY_SYNTAX_OK + 1))
        else
            err "Syntax error in: $fname ($pyfile)"
            PY_SYNTAX_FAIL=$((PY_SYNTAX_FAIL + 1))
        fi
    done
    [ $PY_SYNTAX_FAIL -eq 0 ] && [ $PY_SYNTAX_OK -gt 0 ] && ok "All $PY_SYNTAX_OK Python files pass syntax check"
    [ $PY_SYNTAX_OK -eq 0 ] && info "No Python files found to check"
else
    warn "python3 not installed — skipping Python syntax check"
fi

# ─── 15. PYTHON DEBUG & BAD PATTERNS ─────────────────────────
header "15. Python Debug & Bad Patterns"

for pyfile in $PY_FILES; do
    [ -z "$pyfile" ] && continue
    fname=$(basename "$pyfile")

    # print() statements (exclude if used in CLI scripts that need output)
    PRINT_COUNT=$(gcount '^\s*print(' "$pyfile")
    if [ "$PRINT_COUNT" -gt 3 ]; then
        warn "$fname: $PRINT_COUNT print() statements — consider using logging"
    fi

    # bare except:
    BARE_EXCEPT=$(grep -n 'except:' "$pyfile" 2>/dev/null | grep -v 'except [A-Z]')
    if [ -n "$BARE_EXCEPT" ]; then
        echo "$BARE_EXCEPT" | while read -r line; do
            LINENO=$(echo "$line" | cut -d: -f1)
            err "$fname:$LINENO bare except: — always specify exception type"
        done
    fi
done

PY_BARE=$(grep -rl 'except:' $PY_FILES 2>/dev/null | wc -l)
[ "$PY_BARE" -eq 0 ] && [ -n "$PY_FILES" ] && ok "No bare except: found"

# ─── 16. PYTHON UNUSED IMPORTS ────────────────────────────────
header "16. Python Unused Imports"

for pyfile in $PY_FILES; do
    [ -z "$pyfile" ] && continue
    fname=$(basename "$pyfile")

    # Extract imported names (simple: 'import X' and 'from X import Y')
    grep '^import \|^from .* import ' "$pyfile" 2>/dev/null | while read -r impline; do
        # Get the imported name(s)
        if echo "$impline" | grep -q '^import '; then
            # import X, import X as Y
            MODULE=$(echo "$impline" | sed 's/^import //;s/ as .*//;s/,.*//')
            # For 'import os.path', check 'os'
            SHORTNAME=$(echo "$MODULE" | cut -d. -f1)
        else
            # from X import Y, Z
            NAMES=$(echo "$impline" | sed 's/^from .* import //' | tr ',' '\n' | sed 's/[[:space:]]//g;s/ as .*//')
            for name in $NAMES; do
                [ "$name" = "*" ] && continue
                CLEAN=$(echo "$name" | sed 's/ as .*//')
                # Check if name appears elsewhere in file (excluding import lines)
                USAGE=$(gcount "\b${CLEAN}\b" "$pyfile")
                # Subtract the import line itself
                if [ "$USAGE" -le 1 ]; then
                    warn "$fname: possibly unused import '$CLEAN'"
                fi
            done
            continue
        fi

        # Check if module name appears elsewhere
        USAGE=$(gcount "\b${SHORTNAME}\b" "$pyfile")
        if [ "$USAGE" -le 1 ]; then
            warn "$fname: possibly unused import '$SHORTNAME'"
        fi
    done
done

# ═══════════════════════════════════════════════════════════════
# SECTION D: SHELL SCRIPTS (Checks 17-18)
# ═══════════════════════════════════════════════════════════════

# ─── 17. SHELL: SET -E CHECK ─────────────────────────────────
header "17. Shell Script Safety"

for shfile in $SH_FILES; do
    [ -z "$shfile" ] && continue
    fname=$(basename "$shfile")

    # Check for set -e or set -euo pipefail in first 5 lines
    HEAD=$(head -5 "$shfile" 2>/dev/null)
    if ! echo "$HEAD" | grep -q 'set -e\|set -euo'; then
        warn "$fname: missing 'set -e' — script continues after errors"
    fi

    # Check for unquoted variables (common pattern: $VAR without quotes)
    # Only flag obvious cases: echo $VAR, cd $VAR, etc.
    UNQUOTED=$(grep -n ' \$[A-Z_][A-Z_0-9]*[^"]' "$shfile" 2>/dev/null \
        | grep -v '"\$\|{\$\|\$(\|#\|\/\/' | head -5)
    if [ -n "$UNQUOTED" ]; then
        COUNT=$(echo "$UNQUOTED" | wc -l)
        warn "$fname: $COUNT likely unquoted variable(s) — use \"\$VAR\" for safety"
    fi
done

if [ -z "$SH_FILES" ]; then
    info "No shell scripts found in $SCRIPTS_DIR"
else
    TOTAL_SH=$(echo "$SH_FILES" | wc -w)
    SH_SAFE=$(for shfile in $SH_FILES; do
        head -5 "$shfile" 2>/dev/null | grep -q 'set -e' && echo 1
    done | wc -l)
    [ "$SH_SAFE" -eq "$TOTAL_SH" ] && ok "All $TOTAL_SH shell scripts have set -e"
fi

# ═══════════════════════════════════════════════════════════════
# SECTION E: CROSS-CUTTING (Checks 18-22)
# ═══════════════════════════════════════════════════════════════

# ─── 18. HARDCODED ENDPOINTS ─────────────────────────────────
header "18. Hardcoded Endpoints & IPs"

ALL_SOURCE_FILES="$JS_FILES $PY_FILES $HTML_FILES"

# Hardcoded IPs
for srcfile in $ALL_SOURCE_FILES; do
    [ -z "$srcfile" ] && continue
    fname=$(basename "$srcfile")

    IP_HITS=$(grep -n '192\.168\.\|10\.0\.\|172\.1[6-9]\.\|172\.2[0-9]\.\|172\.3[0-1]\.' "$srcfile" 2>/dev/null \
        | grep -v '\/\/.*192\|#.*192\|<!--')
    if [ -n "$IP_HITS" ]; then
        echo "$IP_HITS" | head -2 | while read -r line; do
            LINENO=$(echo "$line" | cut -d: -f1)
            warn "$fname:$LINENO hardcoded private IP — consider config constant"
        done
    fi
done

# Hardcoded localhost:PORT
for srcfile in $ALL_SOURCE_FILES; do
    [ -z "$srcfile" ] && continue
    fname=$(basename "$srcfile")

    LOCALHOST_HITS=$(grep -n 'localhost:[0-9]\+\|127\.0\.0\.1:[0-9]\+' "$srcfile" 2>/dev/null \
        | grep -v '\/\/.*localhost\|#.*localhost\|<!--')
    if [ -n "$LOCALHOST_HITS" ]; then
        echo "$LOCALHOST_HITS" | head -2 | while read -r line; do
            LINENO=$(echo "$line" | cut -d: -f1)
            warn "$fname:$LINENO hardcoded localhost:PORT — consider config constant"
        done
    fi
done

# ─── 19. TODO / FIXME / HACK TRACKER ─────────────────────────
header "19. TODO / FIXME / HACK Tracker"

TODO_TOTAL=0
FIXME_TOTAL=0
HACK_TOTAL=0

for srcfile in $ALL_SOURCE_FILES $SH_FILES; do
    [ -z "$srcfile" ] && continue

    T=$(gcount 'TODO\b' "$srcfile")
    F=$(gcount 'FIXME\b' "$srcfile")
    H=$(gcount 'HACK\b' "$srcfile")

    TODO_TOTAL=$((TODO_TOTAL + T))
    FIXME_TOTAL=$((FIXME_TOTAL + F))
    HACK_TOTAL=$((HACK_TOTAL + H))
done

DEBT_TOTAL=$((TODO_TOTAL + FIXME_TOTAL + HACK_TOTAL))
if [ "$DEBT_TOTAL" -gt 0 ]; then
    info "Tech debt markers: $TODO_TOTAL TODO, $FIXME_TOTAL FIXME, $HACK_TOTAL HACK"
    # List individual FIXME/HACK (these are more urgent than TODO)
    if [ "$FIXME_TOTAL" -gt 0 ] || [ "$HACK_TOTAL" -gt 0 ]; then
        for srcfile in $ALL_SOURCE_FILES $SH_FILES; do
            [ -z "$srcfile" ] && continue
            fname=$(basename "$srcfile")
            grep -n 'FIXME\|HACK' "$srcfile" 2>/dev/null | head -3 | while read -r line; do
                info "  $fname: $line"
            done
        done
    fi
else
    ok "No TODO/FIXME/HACK markers found"
fi

# ─── 20. DUPLICATE HTML IDS ──────────────────────────────────
header "20. Duplicate HTML IDs"

for htmlfile in $HTML_FILES; do
    fname=$(basename "$htmlfile")

    DUPES=$(grep -oh 'id="[^"]*"' "$htmlfile" 2>/dev/null \
        | sort | uniq -d)

    if [ -n "$DUPES" ]; then
        echo "$DUPES" | while read -r dup; do
            err "$fname: duplicate $dup"
        done
    fi
done

DUP_ID_COUNT=$(for htmlfile in $HTML_FILES; do
    grep -oh 'id="[^"]*"' "$htmlfile" 2>/dev/null | sort | uniq -d
done | wc -l)
[ "$DUP_ID_COUNT" -eq 0 ] && ok "No duplicate IDs found"

# ─── 21. ACCESSIBILITY BASICS ────────────────────────────────
header "21. Accessibility Basics"

A11Y_ISSUES=0

for htmlfile in $HTML_FILES; do
    fname=$(basename "$htmlfile")

    # img without alt
    IMG_NO_ALT=$(grep -n '<img ' "$htmlfile" 2>/dev/null | grep -v 'alt=')
    if [ -n "$IMG_NO_ALT" ]; then
        echo "$IMG_NO_ALT" | while read -r line; do
            LINENO=$(echo "$line" | cut -d: -f1)
            warn "$fname:$LINENO <img> without alt attribute"
        done
        A11Y_ISSUES=1
    fi

    # button without text content or aria-label
    # Simple heuristic: <button...></button> with nothing between or no aria-label
    ICON_BTNS=$(grep -n '<button[^>]*>' "$htmlfile" 2>/dev/null \
        | grep -v 'aria-label\|aria-labelledby\|title=' \
        | grep '></button>\|>\s*<svg\|>\s*<use')
    if [ -n "$ICON_BTNS" ]; then
        echo "$ICON_BTNS" | head -3 | while read -r line; do
            LINENO=$(echo "$line" | cut -d: -f1)
            warn "$fname:$LINENO <button> may lack accessible label (aria-label)"
        done
        A11Y_ISSUES=1
    fi

    # Empty href="#" or src=""
    EMPTY_HREF=$(grep -n 'href="#"\|href=""\|src=""' "$htmlfile" 2>/dev/null)
    if [ -n "$EMPTY_HREF" ]; then
        echo "$EMPTY_HREF" | head -3 | while read -r line; do
            LINENO=$(echo "$line" | cut -d: -f1)
            warn "$fname:$LINENO empty href/src — causes unnecessary requests or scroll-to-top"
        done
        A11Y_ISSUES=1
    fi
done

[ "$A11Y_ISSUES" -eq 0 ] && ok "Basic accessibility checks passed"

# ─── 22. FILE SIZE & COMPLEXITY ───────────────────────────────
header "22. File Size & Complexity"

SIZE_THRESHOLD=500

for srcfile in $JS_FILES $PY_FILES $CSS_FILES; do
    [ -z "$srcfile" ] && continue
    fname=$(basename "$srcfile")

    LINES=$(wc -l < "$srcfile" 2>/dev/null || echo 0)
    LINES=${LINES:-0}
    if [ "$LINES" -gt 800 ]; then
        err "$fname: $LINES lines — strongly consider splitting"
    elif [ "$LINES" -gt "$SIZE_THRESHOLD" ]; then
        warn "$fname: $LINES lines — consider splitting if still growing"
    fi
done

# Tabs vs Spaces consistency
header "22b. Indentation Consistency"

for srcfile in $JS_FILES $PY_FILES $CSS_FILES $HTML_FILES; do
    [ -z "$srcfile" ] && continue
    fname=$(basename "$srcfile")

    HAS_TABS=$(gcount -P '^\t' "$srcfile")
    HAS_SPACES=$(gcount -P '^  ' "$srcfile")

    if [ "$HAS_TABS" -gt 0 ] && [ "$HAS_SPACES" -gt 0 ]; then
        # Only flag if significant mixing (not just 1-2 lines)
        if [ "$HAS_TABS" -gt 3 ] && [ "$HAS_SPACES" -gt 3 ]; then
            warn "$fname: mixed tabs ($HAS_TABS) and spaces ($HAS_SPACES) — pick one"
        fi
    fi
done

# ═══════════════════════════════════════════════════════════════
# FUNCTION INDEX (Info only, not scored)
# ═══════════════════════════════════════════════════════════════

header "Appendix: Function Index"

info "JS functions:"
for jsfile in $JS_FILES; do
    fname=$(basename "$jsfile")
    FUNCS=$(grep -n 'function [a-zA-Z_]' "$jsfile" 2>/dev/null \
        | sed 's/.*function /  /' | sed 's/(.*//' | head -20)
    ARROW_FUNCS=$(grep -nc '=>' "$jsfile")
    NAMED_COUNT=$(gcount 'function [a-zA-Z_]' "$jsfile")
    if [ "$NAMED_COUNT" -gt 0 ]; then
        echo -e "  ${C}$fname: $NAMED_COUNT named + ~$ARROW_FUNCS arrow functions${N}"
    fi
done

if [ -n "$PY_FILES" ]; then
    info "Python functions/classes:"
    for pyfile in $PY_FILES; do
        [ -z "$pyfile" ] && continue
        fname=$(basename "$pyfile")
        FUNCS=$(gcount '^\s*def ' "$pyfile")
        CLASSES=$(gcount '^\s*class ' "$pyfile")
        if [ "$FUNCS" -gt 0 ] || [ "$CLASSES" -gt 0 ]; then
            echo -e "  ${C}$fname: $FUNCS functions, $CLASSES classes${N}"
        fi
    done
fi

# ─── SUMMARY ─────────────────────────────────────────────────
echo ""
echo -e "${C}═══════════════════════════════════════════${N}"
header "SUMMARY"
echo -e "  ${R}Errors:   $ERRORS${N}"
echo -e "  ${Y}Warnings: $WARNINGS${N}"
echo -e "  ${C}Info:     $INFOS${N}"

echo ""
echo "  Scanned:"
JS_COUNT=$(echo "$JS_FILES" | wc -w)
PY_COUNT=$(echo "$PY_FILES" | wc -w)
CSS_COUNT=$(echo "$CSS_FILES" | wc -w)
HTML_COUNT=$(echo "$HTML_FILES" | wc -w)
SH_COUNT=$(echo "$SH_FILES" | wc -w)
echo "    JS: $JS_COUNT  Python: $PY_COUNT  CSS: $CSS_COUNT  HTML: $HTML_COUNT  Shell: $SH_COUNT"

if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo -e "\n  ${G}✓ CLEAN — No issues found${N}\n"
elif [ $ERRORS -eq 0 ]; then
    echo -e "\n  ${Y}⚠ ACCEPTABLE — Warnings only, review when convenient${N}\n"
else
    echo -e "\n  ${R}✗ FIX NEEDED — $ERRORS error(s) should be resolved before next session${N}\n"
fi

exit $ERRORS
