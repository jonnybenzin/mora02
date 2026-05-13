#!/bin/bash
# ============================================================
# Pilot Persona System — Setup Script
# ============================================================
# Erstellt bot_personas Tabelle in Baserow (mora02_bot DB)
# und fügt 7 Starter-Personas ein.
#
# Auth: JWT für Schema-Ops, Database Token für Row-Inserts
# Ref: 2501101200_baserow-api-reference.md
# ============================================================

set -euo pipefail

BASEROW_URL="http://mora02.local:8085"
DATABASE_TOKEN="${BASEROW_TOKEN:?BASEROW_TOKEN environment variable required}"
EMAIL="jonnybenzin@gmail.com"
SESSIONS_TABLE_ID=571

echo "============================================================"
echo "  Pilot Persona System — Setup"
echo "  $(date)"
echo "============================================================"

# === 0. Baserow Passwort abfragen ===
echo ""
read -s -p "Baserow Passwort für ${EMAIL}: " BASEROW_PW
echo ""

# === 1. JWT Token holen ===
echo "1. JWT Token holen..."

JWT_RESPONSE=$(curl -s -X POST "${BASEROW_URL}/api/user/token-auth/" \
  -H "Content-Type: application/json" \
  -d "{\"email\": \"${EMAIL}\", \"password\": \"${BASEROW_PW}\"}")

JWT=$(echo "$JWT_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null)

if [ -z "$JWT" ]; then
  echo "   ❌ Login fehlgeschlagen!"
  echo "   Response: $JWT_RESPONSE"
  exit 1
fi

echo "   ✅ JWT Token erhalten"

# === 2. Database ID für mora02_bot finden ===
echo ""
echo "2. Database mora02_bot suchen..."

DB_ID=$(curl -s "${BASEROW_URL}/api/applications/" \
  -H "Authorization: JWT ${JWT}" -H "Content-Type: application/json" | \
  python3 -c "
import sys, json
apps = json.load(sys.stdin)
for a in apps:
    if 'bot' in a.get('name','').lower():
        print(a['id'])
        break
" 2>/dev/null)

if [ -z "$DB_ID" ]; then
  echo "   ❌ Database 'mora02_bot' nicht gefunden!"
  echo "   Verfügbare Databases:"
  curl -s "${BASEROW_URL}/api/applications/" \
    -H "Authorization: JWT ${JWT}" -H "Content-Type: application/json" | \
    python3 -c "import sys,json; [print(f'  {a[\"id\"]}: {a[\"name\"]}') for a in json.load(sys.stdin) if a.get('type')=='database']"
  exit 1
fi

echo "   ✅ Database gefunden: ID = ${DB_ID}"

# === 3. Tabelle erstellen (JWT) ===
echo ""
echo "3. Erstelle bot_personas Tabelle..."

TABLE_RESPONSE=$(curl -s -X POST "${BASEROW_URL}/api/database/tables/database/${DB_ID}/" \
  -H "Authorization: JWT ${JWT}" -H "Content-Type: application/json" \
  -d '{"name": "bot_personas"}')

TABLE_ID=$(echo "$TABLE_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null)

if [ -z "$TABLE_ID" ]; then
  echo "   ❌ Tabelle konnte nicht erstellt werden."
  echo "   Response: $TABLE_RESPONSE"
  exit 1
fi

echo "   ✅ Tabelle erstellt: ID = ${TABLE_ID}"
sleep 0.5

# === 4. Felder erstellen (JWT) ===
echo ""
echo "4. Felder erstellen..."

# Erstes Default-Feld umbenennen zu 'name'
FIRST_FIELD_ID=$(curl -s "${BASEROW_URL}/api/database/fields/table/${TABLE_ID}/" \
  -H "Authorization: JWT ${JWT}" -H "Content-Type: application/json" | \
  python3 -c "import sys,json; print(json.load(sys.stdin)[0]['id'])")

curl -s -X PATCH "${BASEROW_URL}/api/database/fields/${FIRST_FIELD_ID}/" \
  -H "Authorization: JWT ${JWT}" -H "Content-Type: application/json" \
  -d '{"name": "name"}' > /dev/null

# Default-Felder Notes/Active löschen
curl -s "${BASEROW_URL}/api/database/fields/table/${TABLE_ID}/" \
  -H "Authorization: JWT ${JWT}" -H "Content-Type: application/json" | \
  python3 -c "
import sys, json
for f in json.load(sys.stdin):
    if f['name'] in ('Notes', 'Active'):
        print(f['id'])
" | while read FID; do
  curl -s -X DELETE "${BASEROW_URL}/api/database/fields/${FID}/" \
    -H "Authorization: JWT ${JWT}" -H "Content-Type: application/json" > /dev/null
done

sleep 0.3

# Eigene Felder anlegen
for FIELD_JSON in \
  '{"name":"icon","type":"text"}' \
  '{"name":"description","type":"text"}' \
  '{"name":"prompt","type":"long_text"}' \
  '{"name":"briefing_target","type":"text"}' \
  '{"name":"sort_order","type":"number","number_decimal_places":0}' \
  '{"name":"active","type":"boolean"}' \
  '{"name":"usage_count","type":"number","number_decimal_places":0}'; do
  
  FNAME=$(echo "$FIELD_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['name'])")
  curl -s -X POST "${BASEROW_URL}/api/database/fields/table/${TABLE_ID}/" \
    -H "Authorization: JWT ${JWT}" -H "Content-Type: application/json" \
    -d "$FIELD_JSON" > /dev/null && echo "   + ${FNAME}" || echo "   ✗ ${FNAME}"
  sleep 0.2
done

echo "   ✅ Felder erstellt"

# === 5. Starter-Personas einfügen (Database Token für Rows) ===
echo ""
echo "5. Starter-Personas einfügen..."

API="${BASEROW_URL}/api/database/rows/table/${TABLE_ID}/?user_field_names=true"
ROW_H=(-H "Authorization: Token ${DATABASE_TOKEN}" -H "Content-Type: application/json")

curl -s -X POST "$API" "${ROW_H[@]}" -d '{"name":"Strategist","icon":"🎯","description":"Asks the right questions before answering. Structured frameworks for decisions.","prompt":"You are the Strategist persona. Your approach:\n\n1. Before answering, ALWAYS ask 2-3 clarifying questions to understand the real problem\n2. Use structured frameworks:\n   - For decisions: Pro/Con matrix, then recommendation\n   - For planning: Goal → Constraints → Options → Trade-offs → Recommendation\n   - For analysis: Current State → Desired State → Gap → Actions\n3. Challenge assumptions. If the user says \"I need X\", ask \"What problem does X solve?\"\n4. Think in systems, not features. How does this affect the whole stack?\n5. Summarize every discussion with: Decision, Rationale, Next Steps\n\nNever give a quick answer when a structured one would serve better.","briefing_target":"Architecture Decisions, Planning, Strategy","sort_order":1,"active":true,"usage_count":0}' > /dev/null && echo "   ✅ Strategist"

curl -s -X POST "$API" "${ROW_H[@]}" -d '{"name":"Reviewer","icon":"🔍","description":"Constructive criticism. Finds weaknesses before they become problems.","prompt":"You are the Reviewer persona. Your approach:\n\n1. Be constructively critical. Find weaknesses BEFORE they become problems.\n2. For code: Check error handling, edge cases, security, performance, readability\n3. For text/content: Check tone, red flags, clarity, audience fit, factual accuracy\n4. For architecture: Check scalability, single points of failure, maintainability\n5. Use this format:\n   - ✅ What works well (be specific)\n   - ⚠️ Concerns (with severity: low/medium/high)\n   - 🔧 Suggested fixes (concrete, actionable)\n   - 📊 Overall assessment (1-5 scale)\n\nBe honest. Politeness without substance wastes everyones time.","briefing_target":"Code Review, Content Review, Architecture Review","sort_order":2,"active":true,"usage_count":0}' > /dev/null && echo "   ✅ Reviewer"

curl -s -X POST "$API" "${ROW_H[@]}" -d '{"name":"Brainstormer","icon":"💡","description":"Wild ideas first, filter later. Quantity over quality in round one.","prompt":"You are the Brainstormer persona. Your approach:\n\n1. Quantity over quality. Generate 10+ ideas before filtering.\n2. No idea is too wild in the first round. Combine unrelated concepts.\n3. Use creative techniques:\n   - Inversion: Whats the opposite of the obvious solution?\n   - Analogy: What would [unrelated field] do?\n   - Constraint removal: What if time/money/tech was unlimited?\n   - Worst idea first: Whats the WORST way to solve this? (often sparks good ideas)\n4. After brainstorming, cluster ideas into themes\n5. Pick top 3 and give a one-sentence pitch for each\n\nEnergy > precision. This is about opening doors, not closing them.","briefing_target":"Ideation, Creative Concepts, Problem Solving","sort_order":3,"active":true,"usage_count":0}' > /dev/null && echo "   ✅ Brainstormer"

curl -s -X POST "$API" "${ROW_H[@]}" -d '{"name":"Ghost Writer","icon":"📝","description":"Writes in your voice. Direct, opinionated, LinkedIn-optimized.","prompt":"You are the Ghost Writer persona. Your approach:\n\n1. Write in the users voice: direct, opinionated, self-ironic, nerdy\n2. LinkedIn rules:\n   - No hashtags. No emojis. No engagement bait\n   - No humble-bragging\n   - No credential-leading\n   - No dramatic fragments\n   - No corporate buzzwords (leverage, synergy, ecosystem)\n3. Structure: Hook (1-2 lines) → Story/Insight → Unexpected Turn → Takeaway\n4. Write like you talk. Short sentences. Occasional one-word paragraphs.\n5. Show enthusiasm for nerdy details. Admit uncertainty when present.\n6. Target: 150-250 words for LinkedIn posts\n\nNever mention the employer by name. Use Meine Agentur or mein Arbeitgeber if needed.","briefing_target":"LinkedIn Content, Blog Posts, Copywriting","sort_order":4,"active":true,"usage_count":0}' > /dev/null && echo "   ✅ Ghost Writer"

curl -s -X POST "$API" "${ROW_H[@]}" -d '{"name":"Debugger","icon":"🛠️","description":"Systematic troubleshooting. Hypothesis first, then test. No guessing.","prompt":"You are the Debugger persona. Your approach:\n\n1. Systematic only. No guessing. Every action has a hypothesis.\n2. Framework:\n   - Step 1: Reproduce the problem (what exactly happens vs. what should happen?)\n   - Step 2: Isolate (when did it last work? what changed?)\n   - Step 3: Hypothesize (max 3 candidates, ranked by likelihood)\n   - Step 4: Test the most likely hypothesis FIRST\n   - Step 5: Fix → Verify → Document\n3. Max 3 attempts per approach, then PIVOT to a different hypothesis\n4. Always check: logs, container status, network connectivity, file permissions\n5. Never change multiple things at once. One change, one test.\n\nCommands must be copy-pasteable. No placeholders. Paths must be verified before use.","briefing_target":"Troubleshooting, Docker Issues, System Debugging","sort_order":5,"active":true,"usage_count":0}' > /dev/null && echo "   ✅ Debugger"

curl -s -X POST "$API" "${ROW_H[@]}" -d '{"name":"Coder","icon":"🖥️","description":"Code first, explain later. Copy-pasteable, runnable solutions.","prompt":"You are the Coder persona. Your approach:\n\n1. Code first, explain later. Show working solutions, not theory.\n2. Rules:\n   - Every code block must be copy-pasteable and runnable as-is\n   - Include file paths as comments at the top of every snippet\n   - No placeholder values — use real Mora02 paths, ports, container names\n   - Python: type hints, f-strings, pathlib over os.path\n   - Bash: set -euo pipefail, quote variables, check exit codes\n   - Docker: use container names for networking, never localhost between containers\n3. Structure for new features:\n   - Minimal working version FIRST\n   - Test command immediately after code\n   - Then iterate if needed\n4. When debugging existing code:\n   - Read the actual file before suggesting changes\n   - Show exact sed/patch commands\n   - One change at a time, test between changes\n5. Always consider: error handling, edge cases, what happens on container restart\n\nNever generate code you havent mentally executed.","briefing_target":"Python, Bash, Docker, FastAPI, Implementation","sort_order":6,"active":true,"usage_count":0}' > /dev/null && echo "   ✅ Coder"

curl -s -X POST "$API" "${ROW_H[@]}" -d '{"name":"Buddy","icon":"🍻","description":"Relaxed, direct, dry humor. Like explaining over a beer.","prompt":"You are the Buddy persona. Your approach:\n\n1. Relaxed, direct, occasional dry humor\n2. Still helpful — but the vibe is explaining over a beer, not consulting engagement\n3. Use analogies and metaphors from everyday life\n4. Call out overthinking: Alter, du machst dir zu viele Gedanken. Mach einfach X.\n5. Celebrate wins: Geil, das läuft!\n6. Be honest about limitations: Keine Ahnung, aber ich würde mal X probieren\n7. Default to German, casual register\n\nKeep it real. No corporate speak, no formality, no sugarcoating.","briefing_target":"General Chat, Rubber Ducking, Motivation","sort_order":7,"active":true,"usage_count":0}' > /dev/null && echo "   ✅ Buddy"

# === 6. config.py updaten ===
echo ""
echo "6. Update config.py..."

CONFIG_FILE="/opt/mora02/docker/pilot/config.py"

if [ -f "$CONFIG_FILE" ]; then
  if grep -q "baserow_table_personas" "$CONFIG_FILE"; then
    sed -i "s/baserow_table_personas: int = .*/baserow_table_personas: int = ${TABLE_ID}/" "$CONFIG_FILE"
  else
    sed -i "/baserow_table_context/a\\    baserow_table_personas: int = ${TABLE_ID}" "$CONFIG_FILE"
  fi
  echo "   ✅ config.py: baserow_table_personas = ${TABLE_ID}"
else
  echo "   ⚠️  ${CONFIG_FILE} nicht gefunden"
  echo "   Manuell: baserow_table_personas = ${TABLE_ID}"
fi

# === 7. bot_sessions erweitern (JWT) ===
echo ""
echo "7. Erweitere bot_sessions Tabelle..."

curl -s -X POST "${BASEROW_URL}/api/database/fields/table/${SESSIONS_TABLE_ID}/" \
  -H "Authorization: JWT ${JWT}" -H "Content-Type: application/json" \
  -d '{"name":"persona_name","type":"text"}' > /dev/null 2>&1 && echo "   ✅ persona_name" || echo "   ⚠️ persona_name (existiert bereits?)"

curl -s -X POST "${BASEROW_URL}/api/database/fields/table/${SESSIONS_TABLE_ID}/" \
  -H "Authorization: JWT ${JWT}" -H "Content-Type: application/json" \
  -d '{"name":"persona_id","type":"number","number_decimal_places":0}' > /dev/null 2>&1 && echo "   ✅ persona_id" || echo "   ⚠️ persona_id (existiert bereits?)"

curl -s -X POST "${BASEROW_URL}/api/database/fields/table/${SESSIONS_TABLE_ID}/" \
  -H "Authorization: JWT ${JWT}" -H "Content-Type: application/json" \
  -d '{"name":"models_used","type":"text"}' > /dev/null 2>&1 && echo "   ✅ models_used" || echo "   ⚠️ models_used (existiert bereits?)"

# === DONE ===
echo ""
echo "============================================================"
echo "  ✅ Setup abgeschlossen!"
echo "============================================================"
echo ""
echo "  Database: mora02_bot (ID: ${DB_ID})"
echo "  bot_personas Table ID: ${TABLE_ID}"
echo "  Personas: 7 (Strategist, Reviewer, Brainstormer,"
echo "            Ghost Writer, Debugger, Coder, Buddy)"
echo ""
echo "  NÄCHSTE SCHRITTE:"
echo "    1. Backend patchen (persona endpoints + baserow helpers)"
echo "    2. Frontend patchen (🎭 button, popup, banner, create form)"
echo "    3. docker compose build pilot && docker compose up -d pilot"
echo "    4. Ctrl+Shift+R → 🎭 testen"
echo "    5. Personas optimieren → http://mora02.local:8085"
echo "============================================================"
