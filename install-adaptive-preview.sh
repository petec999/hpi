#!/usr/bin/env bash
# Experimental integrated preview for an existing 1.4.5 Stable installation.
# Usage: bash install-adaptive-preview.sh <immutable commit SHA> [--apply]
set -Eeuo pipefail
umask 077
REF="${1:-}"
MODE="${2:---dry-run}"
[[ "$REF" =~ ^[0-9a-f]{40}$ ]] || { echo "Pass a pinned 40-character Git commit." >&2; exit 2; }
[[ "$MODE" == "--dry-run" || "$MODE" == "--apply" ]] || { echo "Unknown option" >&2; exit 2; }
[[ $# -le 2 ]] || exit 2
if [[ "$MODE" == "--apply" && $EUID != 0 ]]; then
  echo "Run as root." >&2
  exit 1
fi
STAGE="$(mktemp -d /tmp/haier-adaptive-preview.XXXXXXXX)"
trap 'rm -rf -- "$STAGE"' EXIT
BASE="https://raw.githubusercontent.com/petec999/hpi/$REF"
FILES=(
  adaptive/regulator.py adaptive/live_runtime.py adaptive/energy.py
  patches/stable-gpio.py patches/stable-mqtt.py
  tools/install-mqtt-watchdog.py tools/install-1454-core.py
  tools/install-web-ui-v2.py tools/patch-adaptive-preview.py
  tools/patch-core-resources.py tools/patch-serial-charts.py tools/patch-local-auth.py tools/patch-energy.py tools/install-adaptive-preview.py
)
for path in "${FILES[@]}"; do
  mkdir -p "$STAGE/$(dirname "$path")"
  curl -fLSs --retry 3 "$BASE/$path" -o "$STAGE/$path"
done
if [[ "$MODE" == "--apply" ]]; then
  python3 "$STAGE/tools/install-adaptive-preview.py" --apply
else
  python3 "$STAGE/tools/install-adaptive-preview.py"
fi
