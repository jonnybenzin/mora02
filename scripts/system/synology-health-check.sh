#!/bin/bash
NAS_IP="192.168.178.140"
MOUNT_POINT="/home/jonnybenzin/synology-backup"
LOG_FILE="/var/log/synology-health-check.log"

timestamp() {
    date "+%Y-%m-%d %H:%M:%S"
}

send_notification() {
    local title="$1"
    local message="$2"
    sudo -u jonnybenzin DISPLAY=:0 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus \
        notify-send --urgency=critical --icon=dialog-error "$title" "$message"
    echo "[$(timestamp)] CRITICAL: $message" >> "$LOG_FILE"
}

if ! ping -c 1 -W 2 "$NAS_IP" &>/dev/null; then
    send_notification "⚠️ Synology Offline" "Synology NAS ($NAS_IP) ist nicht erreichbar!"
    echo "[$(timestamp)] ERROR: Synology nicht erreichbar" >> "$LOG_FILE"
    exit 1
fi

if ! showmount -e "$NAS_IP" 2>/dev/null | grep -q "/volume1/mora02_borg"; then
    send_notification "⚠️ Synology NFS Problem" "NFS-Export nicht verfügbar!"
    echo "[$(timestamp)] ERROR: NFS-Export nicht verfügbar" >> "$LOG_FILE"
    exit 1
fi

if ! mountpoint -q "$MOUNT_POINT"; then
    echo "[$(timestamp)] WARNING: NFS nicht gemountet - versuche Mount..." >> "$LOG_FILE"
    if mount -t nfs -o vers=3,nolock "$NAS_IP:/volume1/mora02_borg" "$MOUNT_POINT" 2>/dev/null; then
        echo "[$(timestamp)] OK: NFS erfolgreich gemountet" >> "$LOG_FILE"
    else
        send_notification "⚠️ Synology Mount Failed" "Konnte NFS-Share nicht mounten!"
        echo "[$(timestamp)] ERROR: Mount fehlgeschlagen" >> "$LOG_FILE"
        exit 1
    fi
fi

TEST_FILE="$MOUNT_POINT/.health-check-test"
if ! touch "$TEST_FILE" 2>/dev/null; then
    send_notification "⚠️ Synology Read-Only" "NFS-Share ist nur lesbar!"
    echo "[$(timestamp)] ERROR: Keine Schreibrechte" >> "$LOG_FILE"
    exit 1
fi
rm -f "$TEST_FILE"

if [ ! -f "$MOUNT_POINT/config" ]; then
    send_notification "⚠️ Borg Repository Fehler" "Kein gültiges Borg-Repository!"
    echo "[$(timestamp)] ERROR: Borg config nicht gefunden" >> "$LOG_FILE"
    exit 1
fi

echo "[$(timestamp)] OK: Synology Health-Check erfolgreich" >> "$LOG_FILE"
exit 0
