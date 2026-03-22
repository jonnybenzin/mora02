#!/bin/bash
# Docker Compose Down und Up
gnome-terminal -- bash -c '
    echo "═══════════════════════════════════════"
    echo "       MORA02 DOCKER RESTART"
    echo "═══════════════════════════════════════"
    echo
    cd /opt/mora02/docker
    
    echo "Stoppe Container..."
    docker compose down
    echo
    echo "Warte 3 Sekunden..."
    sleep 3
    echo
    echo "Starte Container..."
    docker compose up -d
    echo
    echo "═══════════════════════════════════════"
    echo "Aktueller Status:"
    docker compose ps
    echo "═══════════════════════════════════════"
    echo
    read -p "Druecke Enter zum Schliessen..."
'
