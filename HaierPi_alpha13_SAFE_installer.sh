#!/usr/bin/env bash
# HaierPi 1.4.5 alpha13 SAFE bundle: U2 + compressor mapping + signed SH/SC + MQTT freshness.
# This file does NOT apply legacy MQTT entity cleanup (unverified unique IDs).
# Safe default: --check.  --install requires explicit invocation; --rollback restores backup.
set -Eeuo pipefail
umask 077

SERVICE=haier
APP=/opt/haier
BACKUP_ROOT=/opt/haier-safe-backups
FRESHNESS_SHA256=8bdfde24684512e08e2939dca6d5e4618aee9931aefde5e6f7a067002f47061b
FRESHNESS_URL=https://raw.githubusercontent.com/petec999/hpi/da0372290be8dd85ae7b29643b9a1a97dd5d7512/tools/patch_alpha13_freshness.py
MODE="${1:---check}"
STAGE=''
BACKUP=''
ROLLBACK_NEEDED=0

say() { printf '[HaierPi SAFE] %s\n' "$*"; }
fatal() { say "ERROR: $*" >&2; exit 1; }
usage() {
  cat <<'EOF'
Usage: sudo bash HaierPi_alpha13_SAFE_installer.sh --check
       sudo bash HaierPi_alpha13_SAFE_installer.sh --install
       sudo bash HaierPi_alpha13_SAFE_installer.sh --rollback

--check    Validate sources and prepare patches OFFLINE. Does not touch running HaierPi.
--install  Make full backups of 7 changed Python files, install patch and verify service.
--rollback Restore files from the most recent backup and restart service.
The script never modifies Home Assistant registries or deletes MQTT entities.
EOF
}
[[ "$MODE" == '--help' || "$MODE" == '-h' ]] && { usage; exit 0; }
[[ "$MODE" == '--check' || "$MODE" == '--install' || "$MODE" == '--rollback' ]] || { usage >&2; exit 2; }
(( EUID == 0 )) || fatal 'Run with sudo (root) to preserve file ownership and backups.'
for cmd in python3 cp sha256sum mktemp systemctl flock; do command -v "$cmd" >/dev/null || fatal "Missing command: $cmd"; done

# Block concurrent invocations of the same updater.
exec 9>/run/lock/haierpi-alpha13-safe.lock
flock -n 9 || fatal 'Another safe updater instance is running.'

cleanup() { [[ -z "$STAGE" ]] || rm -rf -- "$STAGE"; }
rollback_files() {
  local directory="$1" lib_dir="$2" name
  [[ -f "$directory/main.py" && -d "$directory/PyHaier" ]] || return 1
  cp -a -- "$directory/main.py" "$APP/main.py" || return 1
  for name in GetTao.py GetTdef.py GetTdTs.py GetTSatPd.py GetTSatPs.py GetThiTho.py; do
    cp -a -- "$directory/PyHaier/$name" "$lib_dir/$name" || return 1
  done
}
on_error() {
  local rc="$?"
  trap - ERR INT TERM
  set +e
  if (( ROLLBACK_NEEDED )) && [[ -n "$BACKUP" ]]; then
    say 'Failure during installation. Restoring the previous files automatically.' >&2
    systemctl stop "$SERVICE" >/dev/null 2>&1 || true
    if rollback_files "$BACKUP" "$LIB"; then
      systemctl start "$SERVICE" || say 'CRITICAL: rollback restored files but service could not start.' >&2
    else
      say "CRITICAL: automatic rollback failed. Backup: $BACKUP" >&2
    fi
  fi
  cleanup
  exit "${rc:-1}"
}
trap cleanup EXIT
trap on_error ERR
trap 'false' INT TERM

if [[ "$MODE" == '--rollback' ]]; then
  [[ -L "$BACKUP_ROOT/LATEST" ]] || fatal "No saved backup pointer: $BACKUP_ROOT/LATEST"
  BACKUP="$(cd -P -- "$BACKUP_ROOT/LATEST" && pwd)"
  [[ "$BACKUP" == "$BACKUP_ROOT"/* && -f "$BACKUP/PyHaier/GetTao.py" ]] || fatal 'Backup directory is invalid.'
  LIB="$(cat "$BACKUP/PyHaier_location")"
  [[ -d "$LIB" ]] || fatal "PyHaier path no longer exists: $LIB"
  say "Restoring backup: $BACKUP"
  systemctl stop "$SERVICE"
  ROLLBACK_NEEDED=0
  rollback_files "$BACKUP" "$LIB"
  systemctl start "$SERVICE"
  sleep 3
  systemctl is-active --quiet "$SERVICE" || fatal 'Restored files, but service is not running; inspect journalctl -u haier.'
  say 'Previous version restored; service is active.'
  exit 0
fi

[[ -f "$APP/main.py" ]] || fatal "Missing $APP/main.py"
# The published alpha13 package has exactly one vendored PyHaier package.
shopt -s nullglob
libs=("$APP"/env/lib/python*/site-packages/PyHaier)
shopt -u nullglob
(( ${#libs[@]} == 1 )) || fatal 'Expected exactly one /opt/haier/env/lib/python*/site-packages/PyHaier directory.'
LIB="${libs[0]}"

STAGE="$(mktemp -d /tmp/haierpi-alpha13-safe.XXXXXXXX)"
mkdir -p "$STAGE/PyHaier"
cp -a -- "$APP/main.py" "$STAGE/main.py"
for name in GetTao.py GetTdef.py GetTdTs.py GetTSatPd.py GetTSatPs.py GetThiTho.py; do
  [[ -f "$LIB/$name" ]] || fatal "Missing $LIB/$name"
  cp -a -- "$LIB/$name" "$STAGE/PyHaier/$name"
done

# The helper is pinned to a specific commit AND checked by SHA256.
# When using the accompanying ZIP it is used locally, with no network needed.
SELF_DIR="$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$SELF_DIR/patch_alpha13_freshness.py" ]]; then
  cp -- "$SELF_DIR/patch_alpha13_freshness.py" "$STAGE/freshness.py"
else
  command -v curl >/dev/null || fatal 'Need curl to fetch the pinned freshness helper.'
  say 'Downloading pinned freshness helper (before any service change)...'
  curl -fsSL --retry 2 --connect-timeout 8 --max-time 30 "$FRESHNESS_URL" -o "$STAGE/freshness.py" || fatal 'Cannot fetch helper. No service changes were made.'
fi
printf '%s  %s\n' "$FRESHNESS_SHA256" "$STAGE/freshness.py" | sha256sum -c --status || fatal 'Freshness helper SHA256 mismatch! No files changed.'

# Preflight: prepare and validate ALL modifications in the temporary directory.
HPI_SAFE_MAIN="$STAGE/main.py" HPI_SAFE_LIB="$STAGE/PyHaier" python3 - <<'PY'
from pathlib import Path
import ast
import os

main_path = Path(os.environ['HPI_SAFE_MAIN'])
lib = Path(os.environ['HPI_SAFE_LIB'])
source = main_path.read_text(encoding='utf-8')
metrics = [
    ('superheat = f"{abs(Ts - TsatPs_act):.1f}"',
     'superheat = f"{Ts - TsatPs_act:.1f}"'),
    ('subcooling = f"{abs(TsatPd_act - Thi):.1f}"',
     'subcooling = f"{TsatPd_act - Thi:.1f}"'),
    ('configure_sensor("Compressor fact", st(\'compinfo\'), "HaierPi_Compfact", "Hz", "frequency", "measurement", "{{ value_json[0] | float }}")',
     'configure_sensor("Compressor fact", st(\'compinfo\'), "HaierPi_Compfact", "Hz", "frequency", "measurement", "{{ value_json[1] | float }}")'),
    ('configure_sensor("Compressor fset", st(\'compinfo\'), "HaierPi_Compfset", "Hz", "frequency", "measurement", "{{ value_json[1] | float }}")',
     'configure_sensor("Compressor fset", st(\'compinfo\'), "HaierPi_Compfset", "Hz", "frequency", "measurement", "{{ value_json[0] | float }}")'),
]
changed = 0
for before, after in metrics:
    if source.count(before) == 1 and source.count(after) == 0:
        source = source.replace(before, after, 1)
        changed += 1
    elif source.count(before) == 0 and source.count(after) == 1:
        pass  # Already patched.
    else:
        raise RuntimeError('Unexpected alpha13 main.py; refusing to modify: ' + before[:78])
ast.parse(source, filename=str(main_path))
main_path.write_text(source, encoding='utf-8')

expected = {
    'GetTao.py': 1, 'GetTdef.py': 1, 'GetTdTs.py': 2,
    'GetTSatPd.py': 2, 'GetTSatPs.py': 2, 'GetThiTho.py': 2,
}
for name, count in expected.items():
    path = lib / name
    text = path.read_text(encoding='utf-8')
    before = text.count(' -= 4095')
    after = text.count(' -= 4096')
    if before == count and after == 0:
        text = text.replace(' -= 4095', ' -= 4096')
    elif before == 0 and after == count:
        pass
    else:
        raise RuntimeError('Unexpected PyHaier U2 decoder: ' + name)
    ast.parse(text, filename=str(path))
    path.write_text(text, encoding='utf-8')
print('U2: 10 locations in six files; MQTT metrics: 4 locations (all validated).')
PY

HPI_MAIN_PY="$STAGE/main.py" python3 "$STAGE/freshness.py"
python3 -m py_compile "$STAGE/main.py" "$STAGE"/PyHaier/*.py
# Staged modules must preserve live ownership/mode after the freshness patcher's atomic write.
chown --reference="$APP/main.py" "$STAGE/main.py"
chmod --reference="$APP/main.py" "$STAGE/main.py"
for name in GetTao.py GetTdef.py GetTdTs.py GetTSatPd.py GetTSatPs.py GetThiTho.py; do
  chown --reference="$LIB/$name" "$STAGE/PyHaier/$name"
  chmod --reference="$LIB/$name" "$STAGE/PyHaier/$name"
done
say 'Preflight PASS: all source patterns verified, Python syntax checked.'
say 'Included: U2 temperatures + compressor fact/fset + signed SH/SC + R141/R241 MQTT freshness.'
say 'Not included: deleting old MQTT entities (unverified IDs).'
if [[ "$MODE" == '--check' ]]; then
  say 'DRY RUN: nothing in /opt/haier has changed. Use --install to apply.'
  exit 0
fi

# Do not patch a non-running service blindly. Preserve source state before touching it.
systemctl is-active --quiet "$SERVICE" || fatal 'Haier service is not active. Investigate before changing any file.'
mkdir -p "$BACKUP_ROOT"
chmod 700 "$BACKUP_ROOT"
BACKUP="$BACKUP_ROOT/backup-$(date +%Y%m%d-%H%M%S)-$$"
mkdir -p "$BACKUP/PyHaier"
cp -a -- "$APP/main.py" "$BACKUP/main.py"
for name in GetTao.py GetTdef.py GetTdTs.py GetTSatPd.py GetTSatPs.py GetThiTho.py; do
  cp -a -- "$LIB/$name" "$BACKUP/PyHaier/$name"
done
printf '%s\n' "$LIB" > "$BACKUP/PyHaier_location"
[[ ! -f /opt/config.ini ]] || cp -a /opt/config.ini "$BACKUP/config.ini.NOT_MODIFIED"
cat > "$BACKUP/rollback.sh" <<'ROLLBACK'
#!/usr/bin/env bash
set -Eeuo pipefail
[[ "$EUID" -eq 0 ]] || { echo 'Run rollback with sudo' >&2; exit 1; }
D="$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
LIB="$(cat "$D/PyHaier_location")"
[[ -f "$D/main.py" && -d "$LIB" ]] || { echo 'Backup is incomplete' >&2; exit 1; }
exec 9>/run/lock/haierpi-alpha13-safe.lock
flock -n 9 || { echo 'Another updater is running' >&2; exit 1; }
systemctl stop haier
cp -a -- "$D/main.py" /opt/haier/main.py
for n in GetTao.py GetTdef.py GetTdTs.py GetTSatPd.py GetTSatPs.py GetThiTho.py; do
  cp -a -- "$D/PyHaier/$n" "$LIB/$n"
done
systemctl start haier
sleep 3
systemctl is-active --quiet haier || { echo 'Files restored; service did not start. Check journalctl -u haier' >&2; exit 1; }
echo 'Rollback successful: original files restored and haier is active.'
ROLLBACK
chmod 700 "$BACKUP/rollback.sh"
ln -sfn "$BACKUP" "$BACKUP_ROOT/LATEST.new"
mv -Tf "$BACKUP_ROOT/LATEST.new" "$BACKUP_ROOT/LATEST"
say "Saved backup: $BACKUP"
say "Manual rollback: sudo bash $BACKUP/rollback.sh"

# From here on, any error triggers restoration of all seven original Python files.
ROLLBACK_NEEDED=1
say 'Stopping haier; applying validated Python files...'
systemctl stop "$SERVICE"
cp -a -- "$STAGE/main.py" "$APP/main.py"
for name in GetTao.py GetTdef.py GetTdTs.py GetTSatPd.py GetTSatPs.py GetThiTho.py; do
  cp -a -- "$STAGE/PyHaier/$name" "$LIB/$name"
done
systemctl start "$SERVICE"

# Detect early crashes/restarts rather than accepting one transient "active" response.
INITIAL_PID="$(systemctl show "$SERVICE" --property=MainPID --value 2>/dev/null || true)"
INITIAL_RESTARTS="$(systemctl show "$SERVICE" --property=NRestarts --value 2>/dev/null || true)"
say 'Checking the service for 30 seconds...'
for n in $(seq 1 30); do
  sleep 1
  systemctl is-active --quiet "$SERVICE" || { say 'Service stopped during smoke test.' >&2; false; }
  NOW_PID="$(systemctl show "$SERVICE" --property=MainPID --value 2>/dev/null || true)"
  NOW_RESTARTS="$(systemctl show "$SERVICE" --property=NRestarts --value 2>/dev/null || true)"
  if [[ "$INITIAL_PID" =~ ^[1-9][0-9]*$ && "$NOW_PID" != "$INITIAL_PID" ]]; then
    say 'Service MainPID changed unexpectedly; rolling back.' >&2
    false
  fi
  if [[ "$INITIAL_RESTARTS" =~ ^[0-9]+$ && "$NOW_RESTARTS" =~ ^[0-9]+$ ]] && (( NOW_RESTARTS > INITIAL_RESTARTS )); then
    say 'Service restarted unexpectedly during smoke test; rolling back.' >&2
    false
  fi
done
ROLLBACK_NEEDED=0
say 'SUCCESS: service stayed active for 30 seconds.'
say "Backup is retained at: $BACKUP"
say "If data/HA behave incorrectly later: sudo bash $BACKUP/rollback.sh"
say 'Check HA telemetry and web UI yourself; an active service does not prove all pump frames are healthy.'