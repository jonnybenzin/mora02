#!/bin/bash
# Dokumentiert Mora02-Verzeichnisstruktur - FOKUS auf System-Konfiguration

OUTPUT_FILE="/opt/mora02/knowledge/archive/$(date +%Y%m%d%H%M)_directory-structure.md"

{
    echo "# Mora02 Verzeichnisstruktur"
    echo "Erstellt: $(date '+%Y-%m-%d %H:%M:%S')"
    echo ""
    
    echo "## Basis-Struktur /opt/mora02"
    echo '```'
    tree -L 2 -a --dirsfirst /opt/mora02 2>/dev/null | head -n 50
    echo '```'
    echo ""
    
    echo "## Docker-Konfiguration (Struktur + wichtige Files)"
    echo '```'
    find /opt/mora02/docker -type f \( -name "*.yml" -o -name "*.yaml" -o -name "Dockerfile" -o -name "*.sh" -o -name "*.env" -o -name "*.conf" \) | sort
    echo '```'
    echo ""
    
    echo "## Scripts (alle Dateien)"
    echo '```'
    ls -lh /opt/mora02/scripts/
    echo '```'
    echo ""
    
    echo "## AI-Modelle (Verzeichnis-Übersicht)"
    echo '```'
    tree -L 2 -d /opt/mora02/ai_models 2>/dev/null || find /opt/mora02/ai_models -maxdepth 2 -type d | sort
    echo '```'
    echo ""
    
    echo "## AI-Modelle (Größenübersicht pro Typ)"
    echo '```'
    du -sh /opt/mora02/ai_models/*/ 2>/dev/null | sort -h
    echo '```'
    echo ""
    
    echo "## Config-Dateien (falls vorhanden)"
    echo '```'
    find /opt/mora02 -maxdepth 3 -type f \( -name "*.conf" -o -name "*.config" -o -name ".env" \) 2>/dev/null | sort
    echo '```'
    echo ""
    
    echo "## Docker Runtime Status"
    echo '```'
    docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"
    echo '```'
    echo ""
    
    echo "## Docker Images"
    echo '```'
    docker images --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}"
    echo '```'
    echo ""
    
    echo "## Docker Volumes"
    echo '```'
    docker volume ls
    echo '```'
    echo ""
    
    echo "## Docker Networks"
    echo '```'
    docker network ls
    echo '```'

} > "$OUTPUT_FILE"

echo "Verzeichnis-Dokumentation erstellt: $OUTPUT_FILE"
