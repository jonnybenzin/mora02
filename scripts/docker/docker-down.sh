#!/bin/bash
gnome-terminal -- bash -c '
    echo "═══════════════════════════════════════"
    echo "       MORA02 DOCKER DOWN"
    echo "═══════════════════════════════════════"
    echo
    cd /opt/mora02/docker

    echo "Stoppe ALLE Container (inkl. aller LLM-Profile)..."
    docker compose --profile "*" down --remove-orphans
    # Sicherheitsnetz: llama-server kann vom llm-switch standalone
    # gestartet worden sein und dem Profil-Tracking entgehen.
    docker rm -f llama-server 2>/dev/null || true
    echo
    echo "═══════════════════════════════════════"
    echo "Aktueller Status:"
    docker compose ps
    echo "═══════════════════════════════════════"
    echo
    read -p "Druecke Enter zum Schliessen..."
'

