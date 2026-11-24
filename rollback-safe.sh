#!/usr/bin/env bash
# Manually restore a snapshot made by install-safe.sh.
set -Eeuo pipefail
[[ ${EUID} -eq 0 ]] || { echo "Root required" >&2; exit 1; }
[[ $# -eq 1 ]] || { echo "Usage: $0 /var/backups/haierpi/<snapshot>" >&2; exit 1; }
BACKUP="$(realpath "$1")"
[[ -f "$BACKUP/metadata.txt" && -s "$BACKUP/app.tar" && -f "$BACKUP/config" ]] ||
    { echo "Invalid backup" >&2; exit 1; }
# metadata is written only by the local privileged installer, in a 0700 directory.
source "$BACKUP/metadata.txt"
[[ -n "${service:-}" && -n "${app:-}" && -n "${config:-}" ]] ||
    { echo "Missing backup metadata" >&2; exit 1; }
# Never move the running app onto the small backup filesystem. A previous
# cross-device mv exhausted overlayfs-root and prevented rollback.
tar -tf "$BACKUP/app.tar" >/dev/null || { echo "Unreadable backup archive" >&2; exit 1; }
APP_PARENT="$(dirname "$app")"
APP_NAME="$(basename "$app")"
APP_KB="$(du -sk "$app" 2>/dev/null | awk '{print $1+0}')"
APP_FREE_KB="$(df -Pk "$APP_PARENT" | awk 'NR==2{print $4}')"
if (( APP_FREE_KB < APP_KB + 32768 )); then
    echo "ERROR: refusing rollback before stopping service: app filesystem needs $((APP_KB + 32768)) KB free; has ${APP_FREE_KB} KB. Free space or move a rescue backup off /opt first." >&2
    exit 1
fi
FAILED_APP="$APP_PARENT/.$APP_NAME.manual-replaced-$(date +%s)-$"
systemctl stop "$service"
if [[ -e "$app" ]]; then mv "$app" "$FAILED_APP"; fi
if tar -xpf "$BACKUP/app.tar" -C "$APP_PARENT" && cp -a "$BACKUP/config" "$config"; then
    rm -rf -- "$FAILED_APP"
    if [[ "$was_active" == 1 ]]; then systemctl start "$service"; fi
    echo "Restored snapshot: $BACKUP"
else
    echo "ERROR: restore failed, reverting to prior app directory" >&2
    rm -rf -- "$app"
    [[ ! -e "$FAILED_APP" ]] || mv "$FAILED_APP" "$app"
    [[ "$was_active" != 1 ]] || systemctl start "$service" || true
    exit 1
fi
