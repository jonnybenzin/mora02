#!/bin/bash
#
# Mora02 System State Snapshot
# Sammelt aktuellen System-Zustand für RAG Indexierung
#

set -e

SNAPSHOT_DIR="/opt/mora02/data/system-snapshot"
TIMESTAMP=$(date +%Y-%m-%d_%H-%M-%S)

echo "[INFO] Mora02 System Snapshot gestartet..."

# Snapshot-Verzeichnis vorbereiten
rm -rf "$SNAPSHOT_DIR"
mkdir -p "$SNAPSHOT_DIR"

echo "[INFO] Sammle Docker Configurations..."
# Docker Compose Files
cp /opt/mora02/docker/docker-compose.yml "$SNAPSHOT_DIR/mora02_docker-compose.yml"

echo "[INFO] Sammle Scripts..."
# Alle Scripts (aber nicht .pyc, .log)
find /opt/mora02/scripts -type f \( -name "*.sh" -o -name "*.py" \) \
    -exec cp {} "$SNAPSHOT_DIR/" \;

echo "[INFO] Erstelle Scripts Overview..."
cat > "$SNAPSHOT_DIR/mora02_scripts_overview.md" << EOF
# Mora02 Scripts Uebersicht
Auto-generiert: $(date '+%Y-%m-%d %H:%M:%S')

EOF

# Liste alle Scripts mit Beschreibung
for script in /opt/mora02/scripts/*.sh /opt/mora02/scripts/*.py; do
    if [ -f "$script" ]; then
        filename=$(basename "$script")
        echo "" >> "$SNAPSHOT_DIR/mora02_scripts_overview.md"
        echo "## $filename" >> "$SNAPSHOT_DIR/mora02_scripts_overview.md"
        echo "**Pfad:** \`$script\`" >> "$SNAPSHOT_DIR/mora02_scripts_overview.md"
        
        # Extrahiere Beschreibung (Bash: ^#, Python: """)
        if [[ "$script" == *.py ]]; then
            # Python: Suche erste Zeile mit """ Docstring
            description=$(grep -m 1 '"""' "$script" 2>/dev/null | head -n 1)
            # Extrahiere Text nach der ersten """ oder Zeile darunter
            description=$(sed -n '/^"""/,/^"""/p' "$script" 2>/dev/null | sed '1d;$d' | head -n 1 | xargs)
        else
            # Bash: Suche erste Kommentarzeile (nicht Shebang, nicht leer)
            description=$(grep "^#" "$script" 2>/dev/null | grep -v "^#!/" | grep -v "^#$" | head -n 1 | sed 's/^# *//')
        fi
        
        if [ -n "$description" ]; then
            echo "**Beschreibung:** $description" >> "$SNAPSHOT_DIR/mora02_scripts_overview.md"
        else
            echo "**Beschreibung:** Keine Beschreibung verfuegbar" >> "$SNAPSHOT_DIR/mora02_scripts_overview.md"
        fi
        echo "" >> "$SNAPSHOT_DIR/mora02_scripts_overview.md"
    fi
echo "[INFO] Sammle Hardware Info..."
{
    echo "=== Mora02 Hardware Uebersicht ==="
    echo "Generiert: $(date '+%Y-%m-%d %H:%M:%S')"
    echo ""
    echo "## GPU"
    nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader 2>/dev/null || echo "NVIDIA GPU nicht erkannt"
    echo ""
    echo "## CPU"
    lscpu | grep -E "Model name|CPU\(s\):|Thread|Socket"
    echo ""
    echo "## RAM"
    echo "Total:" $(free -h | grep "Mem:" | awk '{print $2}')
    sudo dmidecode -t memory | grep -E "Type:|Speed:|Size:" | grep -v "Error"
    echo ""
    echo "## Motherboard"
    sudo dmidecode -t baseboard | grep -E "Manufacturer|Product Name"
    echo ""
    echo "## Storage"
    lsblk -o NAME,SIZE,TYPE,MOUNTPOINT | grep -E "disk|part"
    df -h / /opt/mora02 2>/dev/null | tail -n +2
    echo ""
    echo "## Kühlung/Temperaturen"
    sensors 2>/dev/null | grep -E "Core|Package|temp" || echo "lm-sensors nicht installiert"
    echo ""
    echo "## OS"
    lsb_release -d | cut -f2-
    uname -r
} > "$SNAPSHOT_DIR/mora02_hardware.txt"

done


echo "[INFO] Erstelle Verzeichnisstruktur..."
{
    echo "=== Mora02 Hauptstruktur (Level 3) ==="
    tree -L 3 -I 'cache|logs|__pycache__|*.pyc|node_modules|.git|.venv|data|models--*' /opt/mora02
    echo ""
    echo "=== AI Models (vollstaendige Pfade) ==="
    find /opt/mora02/ai_models -type f \( -name "*.safetensors" -o -name "*.ckpt" -o -name "*.pt" -o -name "*.pth" -o -name "*.bin" \) 2>/dev/null | sort || echo "Keine Models gefunden"
} > "$SNAPSHOT_DIR/mora02_structure.txt"


# Docker Container Status
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" > "$SNAPSHOT_DIR/mora02_docker_status.txt"

echo "[INFO] Sammle AI Models..."
# Ollama Models
echo "=== Ollama Models ===" > "$SNAPSHOT_DIR/mora02_ai_models.txt"
docker exec ollama-sys ollama list >> "$SNAPSHOT_DIR/mora02_ai_models.txt" 2>/dev/null || echo "Ollama nicht erreichbar" >> "$SNAPSHOT_DIR/mora02_ai_models.txt"

# ComfyUI Models
echo "" >> "$SNAPSHOT_DIR/mora02_ai_models.txt"
echo "=== ComfyUI Models ===" >> "$SNAPSHOT_DIR/mora02_ai_models.txt"
if [ -d "/opt/mora02/ai_models" ]; then
    find /opt/mora02/ai_models -type f \( -name "*.safetensors" -o -name "*.ckpt" -o -name "*.pt" -o -name "*.pth" \) \
        -exec basename {} \; | sort >> "$SNAPSHOT_DIR/mora02_ai_models.txt"
else
    echo "Kein ai_models Verzeichnis gefunden" >> "$SNAPSHOT_DIR/mora02_ai_models.txt"
fi

echo "[DONE] System Snapshot abgeschlossen: $SNAPSHOT_DIR"
echo "[INFO] Dateien: $(ls -1 "$SNAPSHOT_DIR" | wc -l)"

