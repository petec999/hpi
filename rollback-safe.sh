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
systemctl stop "$service"
if [[ -e "$app" ]]; then mv "$app" "$BACKUP/manual-replaced-$(date +%s)"; fi
tar -xpf "$BACKUP/app.tar" -C "$(dirname "$app")"
cp -a "$BACKUP/config" "$config"
if [[ "$was_active" == 1 ]]; then systemctl start "$service"; fi
echo "Restored snapshot: $BACKUP"
