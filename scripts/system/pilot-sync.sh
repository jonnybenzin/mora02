#!/bin/bash
# pilot-sync.sh — Full system scan → Baserow bot_context
# Runs on HOST (needs Docker socket + nvidia-smi)
# Usage: bash /opt/mora02/scripts/pilot-sync.sh

BASEROW_URL="http://mora02.local:8085"
BASEROW_TOKEN="${BASEROW_TOKEN:?BASEROW_TOKEN environment variable required}"
TABLE_CONTEXT=572
NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
NOW_LOCAL=$(date '+%Y-%m-%d %H:%M')

echo "=== Pilot Sync @ $NOW_LOCAL ==="

# ── 1. SYSTEM ──
DISK_LINE=$(df -h /opt/mora02 | tail -1)
DISK_USED=$(echo "$DISK_LINE" | awk '{print $3}')
DISK_TOTAL=$(echo "$DISK_LINE" | awk '{print $2}')
DISK_PCT=$(echo "$DISK_LINE" | awk '{print $5}')
RAM_TOTAL=$(free -h | awk 'NR==2{print $2}')
RAM_USED=$(free -h | awk 'NR==2{print $3}')
UPTIME=$(uptime -p)
CONTAINER_COUNT=$(docker ps --format '{{.Names}}' | wc -l)

OUT="# Mora02 System Status\n**Synced:** $NOW_LOCAL\n\n"
OUT+="## System\n| Key | Value |\n|-----|-------|\n"
OUT+="| Disk | $DISK_USED / $DISK_TOTAL ($DISK_PCT) |\n"
OUT+="| RAM | $RAM_USED / $RAM_TOTAL |\n"
OUT+="| Uptime | $UPTIME |\n"
OUT+="| Containers | $CONTAINER_COUNT running |\n\n"

# ── 2. GPU & VRAM ──
GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null || echo "?")
VRAM_USED=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null || echo "0")
VRAM_TOTAL=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null || echo "0")
VRAM_FREE=$((VRAM_TOTAL - VRAM_USED))
GPU_TEMP=$(nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader 2>/dev/null || echo "?")
GPU_POWER=$(nvidia-smi --query-gpu=power.draw --format=csv,noheader,nounits 2>/dev/null || echo "?")
DRIVER=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null || echo "?")
PERSIST=$(nvidia-smi --query-gpu=persistence_mode --format=csv,noheader 2>/dev/null || echo "?")

OUT+="## GPU ($GPU_NAME)\n| Key | Value |\n|-----|-------|\n"
OUT+="| VRAM | ${VRAM_USED} / ${VRAM_TOTAL} MiB (${VRAM_FREE} free) |\n"
OUT+="| Temp | ${GPU_TEMP}C |\n"
OUT+="| Power | ${GPU_POWER}W |\n"
OUT+="| Driver | ${DRIVER} |\n"
OUT+="| Persistence | ${PERSIST} |\n\n"

OUT+="### VRAM per Process\n| Process | VRAM (MiB) |\n|---------|------|\n"
while IFS=',' read -r PNAME PMEM; do
    [ -z "$PNAME" ] && continue
    PNAME=$(echo "$PNAME" | xargs)
    PMEM=$(echo "$PMEM" | xargs)
    SHORT=$(basename "$PNAME" 2>/dev/null || echo "$PNAME")
    OUT+="| $SHORT | $PMEM |\n"
done < <(nvidia-smi --query-compute-apps=process_name,used_memory --format=csv,noheader,nounits 2>/dev/null)
OUT+="\n"

# ── 3. LLM STATUS ──
LLM_MODEL="unknown"
LLM_STATUS="down"
if curl -s --max-time 3 http://localhost:8080/health 2>/dev/null | grep -q "ok"; then
    LLM_STATUS="running"
    # Get model from container env or logs
    LLM_MODEL=$(docker inspect llama-server --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null \
        | grep LLAMA_ARG_MODEL | sed 's|.*=/models/||' || echo "?")
    [ -z "$LLM_MODEL" ] && LLM_MODEL="?"
fi

OUT+="## LLM\n| Key | Value |\n|-----|-------|\n"
OUT+="| Model | $LLM_MODEL |\n"
OUT+="| Status | $LLM_STATUS |\n"
OUT+="| Port | 8080 (llama-server) |\n\n"

# ── 4. CONTAINER & PORTS ──
OUT+="## Ports & Container\n| Container | Port | Image |\n|-----------|------|-------|\n"
while IFS='|' read -r CNAME CPORTS CIMAGE; do
    EXT_PORT=$(echo "$CPORTS" | grep -oP '0\.0\.0\.0:\K[0-9]+' | head -1)
    [ -z "$EXT_PORT" ] && EXT_PORT="internal"
    SHORT_IMAGE=$(echo "$CIMAGE" | sed 's|.*/||' | cut -c1-40)
    OUT+="| $CNAME | $EXT_PORT | $SHORT_IMAGE |\n"
done < <(docker ps --format '{{.Names}}|{{.Ports}}|{{.Image}}' | sort)

# Stopped
STOPPED=$(docker ps -a --filter "status=exited" --format '{{.Names}}' 2>/dev/null)
if [ -n "$STOPPED" ]; then
    OUT+="\n### Stopped\n"
    while IFS= read -r S; do
        OUT+="- $S\n"
    done <<< "$STOPPED"
fi
OUT+="\n"

# ── 5. BACKUP ──
OUT+="## Backup\n"
LAST_BACKUP=$(sudo borg list /home/jonnybenzin/synology-backup --last 1 --format '{name} {time}' 2>/dev/null || echo "unavailable")
OUT+="Last: $LAST_BACKUP\n\n"

# ── 6. CRONTABS ──
CRONTAB_CONTENT=$(crontab -l 2>/dev/null | grep -v '^#' | grep -v '^$')
if [ -n "$CRONTAB_CONTENT" ]; then
    OUT+="## Crontabs\n\`\`\`\n$CRONTAB_CONTENT\n\`\`\`\n\n"
fi

# ── 7. BASEROW TABLES ──
OUT+="## Baserow Tables\n"
BTABLES=$(python3 -c "
import requests, json
r = requests.post('$BASEROW_URL/api/user/token-auth/', json={'email':'jonnybenzin@gmail.com','password':'MaGGan99@'})
jwt = r.json().get('access_token','')
h = {'Authorization': f'JWT {jwt}'}
apps = requests.get('$BASEROW_URL/api/applications/', headers=h).json()
for app in apps:
    if app.get('type') == 'database':
        for t in app.get('tables', []):
            print(f'| {app[\"name\"]} | {t[\"name\"]} | {t[\"id\"]} |')
" 2>/dev/null)
if [ -n "$BTABLES" ]; then
    OUT+="| Database | Table | ID |\n|----------|-------|----|\n$BTABLES\n"
else
    OUT+="Could not retrieve tables.\n"
fi

# ══════════════════════════════════════════
# COST AGGREGATION → bot_costs table
# ══════════════════════════════════════════
TABLE_COSTS=574
TABLE_SESSIONS=571
CURRENT_MONTH=$(date -u +%Y-%m)

echo "Aggregating costs for $CURRENT_MONTH..."
python3 << 'PYEOF'
import requests, json, sys
from datetime import datetime, timezone

import os
BASEROW_URL = "http://mora02.local:8085"
TOKEN = os.environ["BASEROW_TOKEN"]
H = {"Authorization": f"Token {TOKEN}", "Content-Type": "application/json"}
TABLE_SESSIONS = 571
TABLE_COSTS = 574
CURRENT_MONTH = datetime.now(timezone.utc).strftime("%Y-%m")

# Read all sessions
sessions = []
page = 1
while True:
    r = requests.get(f"{BASEROW_URL}/api/database/rows/table/{TABLE_SESSIONS}/?user_field_names=true&size=200&page={page}", headers=H)
    if r.status_code != 200:
        break
    data = r.json()
    sessions.extend(data.get("results", []))
    if not data.get("next"):
        break
    page += 1

# Aggregate per month
months = {}
for s in sessions:
    ended = s.get("ended_at") or ""
    if not ended:
        continue
    try:
        ts = datetime.fromisoformat(ended.replace("Z", "+00:00"))
        m = ts.strftime("%Y-%m")
    except:
        continue
    if m not in months:
        months[m] = {"sessions": 0, "tokens_in": 0, "tokens_out": 0, "qwen": 0, "haiku": 0, "sonnet": 0, "opus": 0, "total": 0}
    cost = float(s.get("cost_usd") or 0)
    model = (s.get("model_used") or "qwen").lower()
    months[m]["sessions"] += 1
    months[m]["tokens_in"] += int(s.get("tokens_in") or 0)
    months[m]["tokens_out"] += int(s.get("tokens_out") or 0)
    months[m]["total"] += cost
    if model in months[m]:
        months[m][model] += cost

# Read existing cost rows
r = requests.get(f"{BASEROW_URL}/api/database/rows/table/{TABLE_COSTS}/?user_field_names=true&size=100", headers=H)
existing = {}
if r.status_code == 200:
    for row in r.json().get("results", []):
        existing[row.get("month")] = row.get("id")

# Upsert each month
for m, d in sorted(months.items()):
    row_data = {
        "month": m,
        "sessions_total": d["sessions"],
        "tokens_in": d["tokens_in"],
        "tokens_out": d["tokens_out"],
        "cost_qwen": round(d["qwen"], 4),
        "cost_haiku": round(d["haiku"], 4),
        "cost_sonnet": round(d["sonnet"], 4),
        "cost_opus": round(d["opus"], 4),
        "cost_total": round(d["total"], 4),
    }
    if m in existing:
        r = requests.patch(f"{BASEROW_URL}/api/database/rows/table/{TABLE_COSTS}/{existing[m]}/?user_field_names=true", headers=H, json=row_data)
        print(f"  Updated: {m} (${d['total']:.4f})")
    else:
        # Delete empty default rows first time
        r = requests.post(f"{BASEROW_URL}/api/database/rows/table/{TABLE_COSTS}/?user_field_names=true", headers=H, json=row_data)
        print(f"  Created: {m} (${d['total']:.4f})")
PYEOF

# ══════════════════════════════════════════
# WRITE TO BASEROW
# ══════════════════════════════════════════
upsert_context() {
    local KEY="$1"
    local VALUE="$2"
    ROW_ID=$(curl -s -H "Authorization: Token $BASEROW_TOKEN" \
        "$BASEROW_URL/api/database/rows/table/$TABLE_CONTEXT/?user_field_names=true&size=50" \
        | python3 -c "
import sys, json
data = json.load(sys.stdin)
for r in data.get('results', []):
    if r.get('key') == '$KEY':
        print(r['id'])
        break
" 2>/dev/null)

    ESCAPED=$(echo "$VALUE" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read()))')
    if [ -n "$ROW_ID" ] && [ "$ROW_ID" != "" ]; then
        curl -s -X PATCH -H "Authorization: Token $BASEROW_TOKEN" -H "Content-Type: application/json" \
            "$BASEROW_URL/api/database/rows/table/$TABLE_CONTEXT/$ROW_ID/?user_field_names=true" \
            -d "{\"value\": $ESCAPED, \"updated_at\": \"$NOW\"}" > /dev/null
        echo "  Updated: $KEY"
    else
        curl -s -X POST -H "Authorization: Token $BASEROW_TOKEN" -H "Content-Type: application/json" \
            "$BASEROW_URL/api/database/rows/table/$TABLE_CONTEXT/?user_field_names=true" \
            -d "{\"key\": \"$KEY\", \"value\": $ESCAPED, \"updated_at\": \"$NOW\"}" > /dev/null
        echo "  Created: $KEY"
    fi
}

echo "Writing to Baserow..."
upsert_context "system_info" "$(echo -e "$OUT")"
upsert_context "last_sync" "$NOW"

echo ""
echo "=== Done ==="
echo "  $CONTAINER_COUNT containers | VRAM ${VRAM_USED}/${VRAM_TOTAL} MiB | LLM: $LLM_MODEL"
