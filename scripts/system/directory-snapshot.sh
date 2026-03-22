#!/bin/bash
# Mora02 Directory Snapshot - Dynamisch

TIMESTAMP=$(date +%y%m%d%H%M)
DATUM=$(date +%Y-%m-%d\ %H:%M)
OUTPUT="/opt/mora02/knowledge/archive/${TIMESTAMP}_directory-structure.md"

cat > "$OUTPUT" << HEADER
# Mora02 Verzeichnisstruktur
**Stand:** $DATUM

---

## Kritische Pfade

| Was | Pfad |
|-----|------|
| **Docker Compose (AKTIV)** | \`/opt/mora02/docker/docker-compose.yml\` |
| **.env File** | \`/opt/mora02/docker/.env\` |
| **LLM Modelle** | \`/opt/mora02/ai_models/llama_cpp/\` |
| **ComfyUI Modelle** | \`/opt/mora02/ai_models/comfyui/\` |
| **System-Docs** | \`/opt/mora02/knowledge/handbook/\` |
| **Asset Outputs** | \`/opt/mora02/output/_default/dify-assets/\` |
| **Borg Backup Mount** | \`/home/jonnybenzin/synology-backup\` |

---

## Hauptstruktur /opt/mora02 (2 Ebenen)

\`\`\`
HEADER

tree -L 2 /opt/mora02 -I 'node_modules|__pycache__|*.pyc|.git|venv*' --dirsfirst >> "$OUTPUT"

cat >> "$OUTPUT" << SCRIPTS

\`\`\`

---

## scripts/ (vollständig)

\`\`\`
SCRIPTS

tree /opt/mora02/scripts -I 'venv*|__pycache__' --dirsfirst >> "$OUTPUT"

cat >> "$OUTPUT" << DOCS

\`\`\`

---

## docs/ (3 Ebenen)

\`\`\`
DOCS

tree -L 3 /opt/mora02/docs --dirsfirst >> "$OUTPUT"

echo '```' >> "$OUTPUT"

# Bestätigung
echo "✓ Snapshot: $OUTPUT"
notify-send "Mora02" "Directory Snapshot erstellt" 2>/dev/null || true
