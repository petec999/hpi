#!/usr/bin/env bash
# Safe wrapper for the existing alpha13 installer.
# Never run the wrapped installer without a restorable snapshot.
set -Eeuo pipefail
umask 077

SERVICE="${HPI_SERVICE:-haier}"
APP_DIR="${HPI_APP_DIR:-/opt/haier}"
CONFIG="${HPI_CONFIG:-/opt/config.ini}"
INSTALLER="${HPI_INSTALLER:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/alpha13.sh}"
ARCHIVE="${HPI_ARCHIVE:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/1.4.5_alpha13.tar.gz}"
BACKUP_ROOT="${HPI_BACKUP_ROOT:-/var/backups/haierpi}"
CHECK_SECONDS="${HPI_CHECK_SECONDS:-20}"
HEALTH_CMD="${HPI_HEALTH_CMD:-}"
KEEP_BACKUP=1
SUCCESS=0
RESTORING=0

die() { echo "ERROR: $*" >&2; exit 1; }
[[ ${EUID} -eq 0 ]] || die "Run as root"
[[ -d "$APP_DIR" && -f "$CONFIG" ]] || die "Installation or configuration missing"
[[ -f "$INSTALLER" && -r "$INSTALLER" ]] || die "Installer missing"
[[ -f "$ARCHIVE" && -r "$ARCHIVE" ]] || die "Pinned archive missing"
[[ "$CHECK_SECONDS" =~ ^[0-9]+$ ]] || die "Bad check duration"
command -v systemctl >/dev/null || die "systemctl not found"
command -v tar >/dev/null || die "tar not found"
command -v python3 >/dev/null || die "python3 not found"
command -v flock >/dev/null || die "flock not found"

# Offline integrity/structure checks before touching the service.
tar -tzf "$ARCHIVE" >/dev/null || die "Corrupted archive"
python3 - "$ARCHIVE" <<'PY'
import sys, tarfile, pathlib
with tarfile.open(sys.argv[1], 'r:gz') as tar:
    for m in tar:
        p=pathlib.PurePosixPath(m.name)
        if p.is_absolute() or '..' in p.parts or m.issym() or m.islnk() or m.isdev():
            raise SystemExit('Unsafe alpha13 archive entry: '+m.name)
PY
bash -n "$INSTALLER" || die "Invalid installer shell syntax"
# The previous release filled overlayfs-root while moving a failed 74 MB
# application across filesystems. Reject the operation before stopping HaierPi.
mkdir -p "$BACKUP_ROOT"
APP_KB="$(du -sk "$APP_DIR" | awk '{print $1}')"
APP_FREE_KB="$(df -Pk "$APP_DIR" | awk 'NR==2{print $4}')"
BACKUP_FREE_KB="$(df -Pk "$BACKUP_ROOT" | awk 'NR==2{print $4}')"
APP_NEED_KB=$(( APP_KB + 32768 ))
BACKUP_NEED_KB=$(( APP_KB * 2 + 32768 ))
if (( APP_FREE_KB < APP_NEED_KB || BACKUP_FREE_KB < BACKUP_NEED_KB )); then
    die "Insufficient rollback space: app filesystem free=${APP_FREE_KB}KB (need ${APP_NEED_KB}KB); backup filesystem free=${BACKUP_FREE_KB}KB (need ${BACKUP_NEED_KB}KB). Original HaierPi unchanged. Use install-diagnostics-light.sh for PR6-PR8."
fi
exec 9>"$BACKUP_ROOT/.install.lock"
flock -n 9 || die "An installation is already running"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="$BACKUP_ROOT/$STAMP-$$"
mkdir -m 700 "$BACKUP"
APP_PARENT="$(dirname "$APP_DIR")"
APP_NAME="$(basename "$APP_DIR")"
OLD_ACTIVE=0
if systemctl is-active --quiet "$SERVICE"; then OLD_ACTIVE=1; fi
printf 'service=%q\napp=%q\nconfig=%q\nwas_active=%s\n' \
    "$SERVICE" "$APP_DIR" "$CONFIG" "$OLD_ACTIVE" >"$BACKUP/metadata.txt"
echo "Backing up $APP_DIR and $CONFIG to $BACKUP"
# Snapshot includes the installed PyHaier environment which source patches alter.
tar -cpf "$BACKUP/app.tar" -C "$APP_PARENT" "$APP_NAME"
cp -a "$CONFIG" "$BACKUP/config"
# Preserve service unit and override definitions for diagnostics, without editing them.
systemctl cat "$SERVICE" >"$BACKUP/service-unit.txt" 2>/dev/null || true
test -s "$BACKUP/app.tar" && test -s "$BACKUP/config" || die "Backup failed"
tar -tf "$BACKUP/app.tar" >/dev/null || die "Backup integrity failure"

restore() {
    local rc="$1"
    trap - ERR INT TERM EXIT
    if [[ "$SUCCESS" == 1 || "$RESTORING" == 1 ]]; then exit "$rc"; fi
    RESTORING=1
    echo "INSTALL FAILED (exit $rc). Restoring snapshot $BACKUP" >&2
    systemctl stop "$SERVICE" || true
    # Move failed install aside instead of deleting evidence.
    if [[ -e "$APP_DIR" ]]; then
        mv "$APP_DIR" "$BACKUP/failed-app" || rm -rf -- "$APP_DIR"
    fi
    if tar -xpf "$BACKUP/app.tar" -C "$APP_PARENT" && cp -a "$BACKUP/config" "$CONFIG"; then
        if [[ "$OLD_ACTIVE" == 1 ]]; then
            systemctl start "$SERVICE" || echo "WARNING: restored service could not start" >&2
        fi
        echo "Rollback completed. Snapshot: $BACKUP" >&2
    else
        echo "CRITICAL: rollback failed; original snapshot remains at $BACKUP" >&2
    fi
    exit "$rc"
}
trap 'restore "$?"' ERR INT TERM EXIT

echo "Running bundled installer (pinned alpha13 archive)"
HPI_ARCHIVE="$ARCHIVE" bash "$INSTALLER"

if [[ "$OLD_ACTIVE" == 1 ]]; then
    systemctl is-active --quiet "$SERVICE" || die "Service did not start"
    sleep "$CHECK_SECONDS"
    systemctl is-active --quiet "$SERVICE" || die "Service exited during health check"
fi
if [[ -n "$HEALTH_CMD" ]]; then
    bash -c "$HEALTH_CMD" || die "Application health command failed"
fi
SUCCESS=1
trap - ERR INT TERM EXIT
printf '%s\n' "SUCCESS: installation verified; rollback snapshot at $BACKUP"
printf '%s\n' "To manually restore: sudo bash $(dirname "$INSTALLER")/rollback-safe.sh '$BACKUP'"
