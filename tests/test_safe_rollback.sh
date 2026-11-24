#!/usr/bin/env bash
# Offline smoke tests of the SAFE wrapper using a temporary fake service.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin" "$TMP/archive"
cat >"$TMP/bin/systemctl" <<'SH'
#!/usr/bin/env bash
set -e
case "$1" in
  is-active) [[ "$(cat "$HPI_FAKE_STATE")" == active ]];;
  stop) echo inactive >"$HPI_FAKE_STATE";;
  start) echo active >"$HPI_FAKE_STATE";;
  cat) echo "[Service]";;
  *) exit 1;;
esac
SH
chmod +x "$TMP/bin/systemctl"
printf 'release file\n' >"$TMP/archive/file.txt"
tar -czf "$TMP/release.tar.gz" -C "$TMP/archive" file.txt
cat >"$TMP/installer.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
echo modified >"$HPI_APP_DIR/status"
echo modified >"$HPI_CONFIG"
if [[ "${HPI_TEST_FAIL:-0}" == 1 ]]; then exit 7; fi
SH
chmod +x "$TMP/installer.sh"

# Use root for the wrapper while isolating all paths in a temporary folder.
run_safe() {
  sudo env PATH="$TMP/bin:$PATH" HPI_FAKE_STATE="$TMP/state" \
    HPI_APP_DIR="$TMP/app" HPI_CONFIG="$TMP/config" \
    HPI_INSTALLER="$TMP/installer.sh" HPI_ARCHIVE="$TMP/release.tar.gz" \
    HPI_BACKUP_ROOT="$TMP/backups" HPI_CHECK_SECONDS=0 \
    HPI_TEST_FAIL="${1:-0}" HPI_HEALTH_CMD="${2:-}" \
    bash "$ROOT/install-safe.sh"
}
reset() {
  mkdir -p "$TMP/app"
  echo original >"$TMP/app/status"
  echo original-config >"$TMP/config"
  echo active >"$TMP/state"
}
reset
run_safe 0
[[ "$(cat "$TMP/app/status")" == modified ]]
[[ "$(cat "$TMP/config")" == modified ]]
[[ -n "$(find "$TMP/backups" -name app.tar -print -quit)" ]]

reset
if run_safe 1; then echo 'Expected installer failure' >&2; exit 1; fi
[[ "$(cat "$TMP/app/status")" == original ]]
[[ "$(cat "$TMP/config")" == original-config ]]
[[ "$(cat "$TMP/state")" == active ]]

reset
if run_safe 0 "false"; then echo 'Expected health check failure' >&2; exit 1; fi
[[ "$(cat "$TMP/app/status")" == original ]]
[[ "$(cat "$TMP/config")" == original-config ]]

reset
printf 'not an archive' >"$TMP/release.tar.gz"
if run_safe 0; then echo 'Expected archive preflight failure' >&2; exit 1; fi
[[ "$(cat "$TMP/app/status")" == original ]]
[[ "$(cat "$TMP/state")" == active ]]
echo "SAFE rollback smoke tests PASS"
