#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
ROOT="$(cd "$(dirname "$0")" && pwd)"
CORE=/opt/haier/main.py
PATCH="$ROOT/tools/install-web-ui-v2.py"
case "${1:-}" in
  --dry-run) exec python3 "$PATCH" --dry-run ;;
  "") ;;
  *) echo "Usage: $0 [--dry-run]" >&2; exit 2 ;;
esac
[[ $EUID == 0 ]] || { echo "Run as root" >&2; exit 1; }
systemctl is-active --quiet haier
exec 9>/run/lock/haierpi-1453.lock
flock -n 9
python3 "$PATCH" --dry-run
if grep -Fq '# HOME-IOT WEB UI V2 BEGIN' "$CORE"; then
  echo "Already installed; no restart."
  exit 0
fi
for col in VFS-OPTIONS FS-OPTIONS; do
  flags="$(findmnt -n -T "$CORE" -o "$col")"
  [[ ",$flags," == *,rw,* ]] || { echo "Read-only mount: refusing to alter mount flags." >&2; exit 1; }
done
backup="$(mktemp /opt/haier/.main-before-webv2-wrapper.XXXXXXXX)"
cp -p "$CORE" "$backup"
python3 "$PATCH"
if ! (systemctl restart haier && sleep 5 && systemctl is-active --quiet haier && sleep 3 && systemctl is-active --quiet haier); then
  echo "Startup failed; restoring $backup" >&2
  cp -p "$backup" "$CORE"
  sync
  systemctl restart haier || true
  exit 1
fi
echo "Haier service active. Open /v2/ on the existing HaierPi URL."
echo "Rollback copy: $backup"
echo "Check actual panel telemetry and MQTT watchdog in journal."
