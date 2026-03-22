#!/bin/bash
# Borg Prune – Dry Run (Mora02)
# Behalte:
# - alle Backups der letzten 7 Tage
# - dann 1 pro Tag (ca. 30 Tage)
# - dann 1 pro Woche (ca. 1 Jahr)
# - dann 1 pro Monat (älter als 1 Jahr)

REPO="/home/jonnybenzin/synology-backup"
export BORG_PASSPHRASE='MaGGan99@'

echo "═══════════════════════════════════════"
echo "   BORG PRUNE – DRY RUN (KEIN LOESCHEN)"
echo "═══════════════════════════════════════"
echo
echo "Repository: $REPO"
echo
echo "Regel:"
echo "  - keep-within=7d"
echo "  - keep-daily=30"
echo "  - keep-weekly=52"
echo "  - keep-monthly=12"
echo

borg prune --dry-run --list \
  --keep-within=7d \
  --keep-daily=30 \
  --keep-weekly=52 \
  --keep-monthly=12 \
  "$REPO"

echo
echo "Hinweis: 'Keeping archive' = bleibt, 'Would prune' = wuerde geloescht."
echo "Wenn alles logisch aussieht, verwende das Live-Skript."
echo

