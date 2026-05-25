#!/bin/bash
# Backup-Liste im Terminal anzeigen
gnome-terminal --geometry=140x35 -- bash -c '
    echo "═══════════════════════════════════════"
    echo "       BORG BACKUP LISTE"
    echo "═══════════════════════════════════════"
    echo
    # Passphrase direkt in sudo-Befehl übergeben
    sudo bash -c "export BORG_PASSPHRASE=\"MaGGan99@\"; borg list /home/jonnybenzin/synology-backup"
    echo
    echo "═══════════════════════════════════════"
    COUNT=$(sudo bash -c "export BORG_PASSPHRASE=\"MaGGan99@\"; borg list /home/jonnybenzin/synology-backup 2>/dev/null" | wc -l)
    echo "Anzahl Backups: $COUNT"
    echo "═══════════════════════════════════════"
    echo

    # Warnung ab 500 Backups
    if [ "$COUNT" -gt 500 ]; then
        echo "⚠ Achtung: Du hast mehr als 500 Backups im Borg-Repository."
        echo "   Bitte denke darüber nach, alte Backups zu reduzieren."
        echo "   Siehe Anleitung: /opt/mora02/knowledge/archive/202512261053_borg_reduction.md"
        echo "   Dry Run: /opt/mora02/scripts/backup/borg-prune-dryrun.sh"
        echo "   Live (nicht ohne dryrun!): /opt/mora02/scripts/backup/borg-prune-live.sh"
        echo
    fi

    read -p "Druecke Enter zum Schliessen..."
'

