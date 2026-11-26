#!/usr/bin/env bash
# HaierPi 1.4.5_4 on existing compatible Stable; never replace the core archive.
set -Eeuo pipefail
umask 077
ROOT="$(cd "$(dirname "$0")" && pwd)"
case "${1:-}" in
  --dry-run) exec python3 "$ROOT/tools/install-1454-core.py" --diff ;;
  --core-only|"") ;;
  *) echo "Usage: $0 [--core-only|--dry-run]" >&2; exit 2 ;;
esac
[[ $EUID == 0 ]] || { echo "Run as root" >&2; exit 1; }
systemctl is-active --quiet haier
python3 "$ROOT/tools/install-1454-core.py"
for file in /opt/haier/main.py /opt/haier/HPi/GPIO.py; do
  for column in VFS-OPTIONS FS-OPTIONS; do
    opts="$(findmnt -n -T "$file" -o "$column")"
    [[ ",$opts," != *,ro,* ]] || { echo "Read-only storage: refusing installation without remount" >&2; exit 1; }
  done
done
python3 "$ROOT/tools/install-1454-core.py" --apply
if [[ "${1:-}" != --core-only ]]; then
  bash "$ROOT/install-diagnostics-light.sh"
fi
echo "1.4.5_4 core installation complete. Verify telemetry and heartbeat."
