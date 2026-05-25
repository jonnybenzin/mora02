#!/bin/bash
# Borg Prune – Dry Run (Mora02)
# Behalte:
# - alle Backups der letzten 7 Tage
# - dann 1 pro Tag (ca. 30 Tage)
# - dann 1 pro Woche (ca. 1 Jahr)
# - dann 1 pro Monat (älter als 1 Jahr)

REPO="/home/jonnybenzin/synology-backup"

echo "═══════════════════════════════════════"
echo "   BORG PRUNE – DRY RUN (KEIN LOESCHEN)"
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

# Borg-Repo gehört root (NFS-Mount via Synology) → sudo + Passphrase im Subshell.
sudo bash -c "export BORG_PASSPHRASE='MaGGan99@'; borg prune --dry-run --list \
  --keep-within=7d \
  --keep-daily=14 \
  --keep-weekly=8 \
  --keep-monthly=12 \
  '$REPO'"

echo
echo "Hinweis: 'Keeping archive' = bleibt, 'Would prune' = wuerde geloescht."
echo "Wenn alles logisch aussieht, verwende das Live-Skript."
echo

