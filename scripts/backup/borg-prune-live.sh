#!/bin/bash
# Borg Prune – Live (Mora02)
# Behalte:
# - alle Backups der letzten 7 Tage
# - dann 1 pro Tag (ca. 30 Tage)
# - dann 1 pro Woche (ca. 1 Jahr)
# - dann 1 pro Monat (älter als 1 Jahr)

REPO="/home/jonnybenzin/synology-backup"

echo "═══════════════════════════════════════"
echo "   BORG PRUNE – LIVE (LOESCHT ALTES)"
echo "═══════════════════════════════════════"
echo
echo "Repository: $REPO"
echo
echo "Regel:"
echo "  - keep-within=7d"
echo "  - keep-daily=14"
echo "  - keep-weekly=8"
echo "  - keep-monthly=12"
echo
read -p "Bist du sicher, dass du fortfahren willst? [ja/NEIN]: " CONFIRM

if [ "$CONFIRM" != "ja" ]; then
  echo "Abgebrochen."
  exit 0
fi

# Borg-Repo gehört root (NFS-Mount via Synology) → sudo + Passphrase im Subshell.
sudo bash -c "export BORG_PASSPHRASE='MaGGan99@'; borg prune --list \
  --keep-within=7d \
  --keep-daily=14 \
  --keep-weekly=8 \
  --keep-monthly=12 \
  '$REPO'"

echo
echo "Fertig. Alte Backups wurden gemaess der Regel entfernt."
echo

