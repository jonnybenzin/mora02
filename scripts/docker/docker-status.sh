#!/bin/bash
# Docker Compose Status anzeigen
gnome-terminal --geometry=200x35 -- bash -c '
    echo "═══════════════════════════════════════"
    echo "       MORA02 DOCKER STATUS"
    echo "═══════════════════════════════════════"
    echo
    cd /opt/mora02/docker
    docker compose ps
    echo
    echo "═══════════════════════════════════════"
    echo "Docker System Info:"
    docker system df
    echo "═══════════════════════════════════════"
    echo
    read -p "Druecke Enter zum Schliessen..."
'
