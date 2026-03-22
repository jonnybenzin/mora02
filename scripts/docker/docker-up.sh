#!/bin/bash
gnome-terminal -- bash -c '
    echo "═══════════════════════════════════════"
    echo "       MORA02 DOCKER UP"
    echo "═══════════════════════════════════════"
    echo
    cd /opt/mora02/docker

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

