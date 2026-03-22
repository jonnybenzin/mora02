#!/bin/bash
# Backup ausführen mit Terminal-Feedback
gnome-terminal -- bash -c '
    echo "═══════════════════════════════════════"
    echo "       MORA02 SYSTEM BACKUP"
    echo "═══════════════════════════════════════"
    echo
    sudo /root/backup-fullsystem.sh
    echo
    echo "═══════════════════════════════════════"
    if [ $? -eq 0 ]; then
        echo "✓ Backup erfolgreich abgeschlossen!"
    else
        echo "✗ Fehler beim Backup!"
    fi
    echo "═══════════════════════════════════════"
    echo
    read -p "Druecke Enter zum Schliessen..."
'
