#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
ROOT="$(cd "$(dirname "$0")" && pwd)"
CORE=/opt/haier/main.py
PATCH="$ROOT/tools/install-web-ui-v2-pressure.py"
case "${1:-}" in
  --dry-run) exec python3 "$PATCH" --dry-run ;;
  "") ;;
  *) echo "Usage: $0 [--dry-run]" >&2; exit 2 ;;
esac
[[ $EUID == 0 ]] || { echo "Run as root" >&2; exit 1; }
systemctl is-active --quiet haier
exec 9>/run/lock/haierpi-1453.lock
flock -n 9
check="$(python3 "$PATCH" --dry-run)"
echo "$check"
if [[ "$check" == "Web UI v2 already current." ]]; then
  echo "Already installed; no restart."
  exit 0
fi
for col in VFS-OPTIONS FS-OPTIONS; do
  flags="$(findmnt -n -T "$CORE" -o "$col")"
  [[ ",$flags," == *,rw,* ]] || { echo "Read-only mount: refusing to alter mount flags." >&2; exit 1; }
done
# Validate the current service and the new invocation independently. Cached
# snapshots are not a proof of continuous RS485 health; startup from N.A.
# must nevertheless produce valid water and compressor measurements.
invocation() {
  systemctl show haier.service -p InvocationID --value
}
has_pump_snapshot() {
  local id="$1"
  [[ "$id" =~ ^[0-9a-f]{32}$ && "$id" != 00000000000000000000000000000000 ]] || return 1
  journalctl -u haier.service "_SYSTEMD_INVOCATION_ID=$id" --since '3 minutes ago' -n 600 --no-pager -o cat |
    python3 -c '
import json,sys,math
last=None
for line in sys.stdin:
    marker="status_snapshot: "
    if marker in line:
        try:
            last=json.loads(line.split(marker,1)[1])
        except (ValueError,TypeError):
            last=None
def valid(key,length):
    v=last.get(key) if isinstance(last,dict) else None
    return isinstance(v,list) and len(v)>=length and all(type(x) in (int,float) and math.isfinite(x) for x in v[:length])
sys.exit(0 if valid("twitwo",2) and valid("compinfo",5) and valid("pdps",4) else 1)
'
}
old_id="$(invocation)"
if ! has_pump_snapshot "$old_id"; then
  echo "Cannot establish working pre-install pump baseline from the service journal; no changes made." >&2
  exit 1
fi
backup="$(mktemp /opt/haier/.main-before-webv2-wrapper.XXXXXXXX)"
cp -p "$CORE" "$backup"
python3 "$PATCH"
healthy=0
if systemctl restart haier; then
  echo "Checking new service invocation for actual pump telemetry..."
  for ((i=0; i<24; i++)); do
    sleep 5
    if ! systemctl is-active --quiet haier; then
      break
    fi
    new_id="$(invocation)"
    if [[ "$new_id" != "$old_id" ]] && has_pump_snapshot "$new_id"; then
      healthy=1
      break
    fi
  done
fi
if [[ "$healthy" != 1 ]]; then
  echo "New service did not demonstrate pump telemetry; restoring $backup" >&2
  cp -p "$backup" "$CORE"
  sync
  if ! systemctl restart haier; then
    echo "Rollback restart failed; inspect systemctl status haier." >&2
    exit 1
  fi
  for ((i=0; i<24; i++)); do
    sleep 5
    if systemctl is-active --quiet haier && has_pump_snapshot "$(invocation)"; then
      echo "Rollback: pump telemetry observed."
      exit 1
    fi
  done
  echo "Rollback completed but pump telemetry not verified; inspect journal." >&2
  exit 1
fi
echo "Haier service active; new invocation has valid water, compressor and pressure data."
echo "Open /v2/ on the existing HaierPi URL."
echo "Rollback copy: $backup"
echo "Check actual panel telemetry and MQTT watchdog in journal."
