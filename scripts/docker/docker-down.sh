#!/bin/bash
gnome-terminal -- bash -c '
    echo "═══════════════════════════════════════"
    echo "       MORA02 DOCKER DOWN"
    echo "═══════════════════════════════════════"
    echo
    cd /opt/mora02/docker

    echo "Stoppe Container..."
    docker compose down
    echo
    echo "═══════════════════════════════════════"
    echo "Aktueller Status:"
    docker compose ps
    echo "═══════════════════════════════════════"
    echo
    read -p "Druecke Enter zum Schliessen..."
'

