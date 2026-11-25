#!/usr/bin/env bash
# HaierPi 1.4.5_3: diagnostics + MQTT readback watchdog on an existing compatible core.
set -Eeuo pipefail
umask 077
ROOT="$(cd "$(dirname "$0")" && pwd)"
CORE=/opt/haier/main.py
PATCH="$ROOT/tools/install-mqtt-watchdog.py"
MODE=all
case "${1:-}" in
  "") ;;
  --watchdog-only) MODE=watchdog ;;
  --dry-run) exec python3 "$PATCH" --path "$CORE" --dry-run ;;
  *) echo "Usage: $0 [--watchdog-only|--dry-run]" >&2; exit 2 ;;
esac
[[ $EUID == 0 ]] || { echo "Run as root" >&2; exit 1; }
systemctl is-active --quiet haier
python3 "$PATCH" --path "$CORE" --dry-run
exec 9>/run/lock/haierpi-1453.lock
flock -n 9
has_ro(){ [[ ",$1," == *,ro,* ]]; }
opt_target="$(findmnt -n -T "$CORE" -o TARGET)"
vfs="$(findmnt -n -T "$CORE" -o VFS-OPTIONS)"
fs="$(findmnt -n -T "$CORE" -o FS-OPTIONS)"
base_changed=0
bind_changed=0
base=""
base_vfs=""
restore_mounts(){
  local rc=0
  sync
  if (( bind_changed )); then
    if mount -o remount,bind,ro /opt; then bind_changed=0; else rc=1; fi
  fi
  if (( base_changed )); then
    if mount -o remount,ro "$base" /mnt; then
      base_changed=0
      if ! has_ro "$base_vfs"; then mount -o remount,bind,rw /mnt || rc=1; fi
    else rc=1
    fi
  fi
  return "$rc"
}
cleanup(){
  local rc=$?
  trap - EXIT
  restore_mounts || { echo "ERROR: mount restoration failed; check findmnt /opt and /mnt" >&2; rc=1; }
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
if has_ro "$fs"; then
  src="$(findmnt -n -T "$CORE" -o SOURCE)"
  base="$(findmnt -n -M /mnt -o SOURCE)"
  base_vfs="$(findmnt -n -M /mnt -o VFS-OPTIONS)"
  [[ "$opt_target" == /opt && "$src" == "$base""[/opt_big]" && "$base" == /dev/* &&
     "$(findmnt -n -M /mnt -o FSTYPE)" == f2fs &&
     "$(findmnt -n -M /ro -o SOURCE)" == "$base" ]] ||
    { echo "Unrecognized read-only layout; refusing to remount" >&2; exit 1; }
  kernel="$(dmesg)"
  if grep -Eiq 'F2FS-fs.*(error|corrupt|checkpoint.*fail)|I/O error.*mmcblk|mmcblk.*I/O error' <<<"$kernel"; then
    echo "Possible storage error; refusing read-write remount" >&2
    exit 1
  fi
  base_changed=1
  mount -o remount,rw "$base" /mnt
fi
if has_ro "$vfs"; then
  [[ "$opt_target" == /opt ]] || { echo "Unexpected read-only mount; refusing" >&2; exit 1; }
  bind_changed=1
  mount -o remount,bind,rw /opt
fi
if has_ro "$(findmnt -n -T "$CORE" -o VFS-OPTIONS)" ||
   has_ro "$(findmnt -n -T "$CORE" -o FS-OPTIONS)"; then
  echo "Still read-only; no installation performed" >&2
  exit 1
fi
if [[ "$MODE" == all ]]; then
  bash "$ROOT/install-diagnostics-light.sh"
fi
if grep -Fq '# HOME-IOT MQTT WATCHDOG v2' "$CORE"; then
  echo "Watchdog already installed; no core restart needed."
else
  backup="$(mktemp /opt/haier/.main-before-1453.XXXXXXXX)"
  cp -p "$CORE" "$backup"
  python3 "$PATCH" --path "$CORE"
  if ! (systemctl restart haier && sleep 5 && systemctl is-active --quiet haier); then
    echo "Core startup failed; restoring $backup" >&2
    cp -p "$backup" "$CORE"
    sync
    systemctl restart haier || true
    exit 1
  fi
  echo "Core startup OK; rollback copy: $backup"
fi
restore_mounts
trap - EXIT
echo "HaierPi 1.4.5_3 installation complete. Confirm heartbeat in journalctl -u haier."
