#!/usr/bin/env bash
# Low-footprint, RAM-only MQTT diagnostics: cycles + refrigeration circuit.
# Never changes /opt/haier. Stops/retires old SQLite historian service.
# The core fixes #1-#4 must already be installed separately.
set -Eeuo pipefail
umask 077

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP="/opt/haierpi-diagnostics"
DATA="/var/lib/haierpi"
BACKUPS="/var/backups/haierpi"
CORE="/opt/haier"
CONFIG="/opt/config.ini"
SERVICE=haier
STAGE=""
SNAP=""
READY=0
CHANGED=0
LOCKED=0
UNITS=(haierpi-cycles haierpi-circuit)
LEGACY_UNITS=(haierpi-pr6 haierpi-pr7 haierpi-pr8)
ALL_UNITS=("${UNITS[@]}" "${LEGACY_UNITS[@]}")

err(){ echo "ERROR: $*" >&2; exit 1; }
available_kb(){ df -Pk "$1" | awk 'NR==2{print $4}'; }
size_kb(){ du -sk "$1" 2>/dev/null | awk '{print $1+0}'; }
[[ $EUID == 0 ]] || err "Run as root"
[[ -f "$CORE/main.py" && -f "$CONFIG" ]] || err "Original HaierPi installation not found"
command -v systemctl >/dev/null || err "systemctl required"
command -v python3 >/dev/null || err "python3 required"
command -v flock >/dev/null || err "flock required"
command -v useradd >/dev/null || err "useradd required"
python3 - <<'PY'
import sys
assert sys.version_info >= (3,9), "Python 3.9+ required"
PY

# Core must remain available; diagnostics require R141/R241 health signals.
systemctl is-active --quiet "$SERVICE" || err "Core HaierPi not active; refusing to install diagnostics"
grep -q 'r141_fresh' "$CORE/main.py" && grep -q 'r241_fresh' "$CORE/main.py" ||
  err "Core freshness signals #4 absent. Apply core fix separately, not using this light installer"

# Check /tmp *before* generating the shared venv. On stock HaierPi /tmp
# is a separate RAM-backed tmpfs. Refuse early instead of exhausting RAM.
# A 48 MiB initial allowance and 12 MiB post-stage reserve are conservative
# for the small Python 3.9 venv + one pinned paho-mqtt dependency.
TMP_FREE_KB="$(available_kb /tmp)"
(( TMP_FREE_KB >= 49152 )) ||
    err "/tmp has ${TMP_FREE_KB}KB free; require at least 49152KB before staging. Nothing changed."
echo "SPACE PREFLIGHT: /=$(available_kb /)KB, /opt=$(available_kb /opt)KB, /tmp=${TMP_FREE_KB}KB free"

# First build the single shared venv in RAM-backed /tmp, before touching services.
STAGE="$(mktemp -d /tmp/hpi-light.XXXXXXXX)"
cleanup(){ [[ -z "$STAGE" ]] || rm -rf -- "$STAGE"; }
trap cleanup EXIT
python3 "$ROOT/diagnostics/derive_mqtt_env.py" --config "$CONFIG" --output "$STAGE/mqtt.env"
python3 -m venv "$STAGE/.venv"
"$STAGE/.venv/bin/python" -m pip install --disable-pip-version-check 'paho-mqtt>=1.6,<2'
"$STAGE/.venv/bin/python" -c 'import paho.mqtt.client'
mkdir -p "$STAGE/code"
cp -a "$ROOT/diagnostics" "$STAGE/code/"
# Ensure the original stage is not mounted on an unexpectedly tiny filesystem.
if (( $(available_kb "$STAGE") < 12288 )); then
    err "/tmp has less than 12MiB remaining after staging; original controller unchanged"
fi

# Preflight using actual staged size, existing installations, and backup data size.
install_kb="$(size_kb "$STAGE/.venv")"
install_kb=$((install_kb + $(size_kb "$STAGE/code") + 1024))
legacy_kb=0
for x in "$APP" /opt/haierpi-pr6 /opt/haierpi-pr7 /opt/haierpi-pr8; do
    [[ ! -e "$x" ]] || legacy_kb=$((legacy_kb + $(size_kb "$x")))
done
data_kb=0
[[ ! -e "$DATA" ]] || data_kb="$(size_kb "$DATA")"
# Never count old install as reclaimed when deciding whether rollback has room.
need_opt=$((install_kb + 20480))
need_root=$((legacy_kb + data_kb + 30720))
[[ $(available_kb /opt) -ge $need_opt ]] ||
    err "/opt needs at least ${need_opt} KB free for a staged shared Python environment; have $(available_kb /opt) KB"
[[ $(available_kb /var/backups) -ge $need_root ]] ||
    err "System backup volume needs at least ${need_root} KB free; have $(available_kb /var/backups) KB"
echo "SPACE OK: /opt needs ${need_opt} KB, backups need ${need_root} KB, /tmp has $(available_kb "$STAGE") KB remaining"
# Recheck each relevant mount immediately before taking a backup. The full
# installer never runs in this mode; the existing core remains untouched.
(( $(available_kb /opt) >= need_opt )) ||
    err "/opt free space dropped during staging; refusing before service changes"
(( $(available_kb "$BACKUPS") >= need_root )) ||
    err "Backup volume free space dropped during staging; refusing before service changes"

mkdir -p "$BACKUPS"
exec 8>"$BACKUPS/.diagnostics-light.lock"
flock -n 8 || err "Another diagnostics installer is already running"
SNAP="$BACKUPS/diag-light-$(date -u +%Y%m%dT%H%M%SZ)-$$"
mkdir -m 700 "$SNAP"

# Save existing service state and config, data and code before any modification.
: > "$SNAP/paths"
for path in "$APP" /opt/haierpi-pr6 /opt/haierpi-pr7 /opt/haierpi-pr8 \
            "$DATA" /etc/haierpi-diagnostics.env \
            /etc/haierpi-pr6.env /etc/haierpi-pr7.env /etc/haierpi-pr8.env \
            /etc/systemd/system/haierpi-pr6.service \
            /etc/systemd/system/haierpi-pr7.service \
            /etc/systemd/system/haierpi-pr8.service \
            /etc/systemd/system/haierpi-cycles.service \
            /etc/systemd/system/haierpi-circuit.service; do
    if [[ -e "$path" || -L "$path" ]]; then
        echo "${path#/}" >> "$SNAP/paths"
    fi
done
for unit in "${ALL_UNITS[@]}"; do
    systemctl is-enabled --quiet "$unit.service" && touch "$SNAP/$unit.enabled" || true
    systemctl is-active --quiet "$unit.service" && touch "$SNAP/$unit.active" || true
done
tar -czpf "$SNAP/previous.tar.gz" -C / -T "$SNAP/paths" ||
    err "Could not create backup; no service changed"
tar -tzf "$SNAP/previous.tar.gz" >/dev/null || err "Backup archive invalid"
sync

rollback(){
    local status="$?"
    trap - ERR INT TERM EXIT
    if [[ $READY == 1 ]]; then cleanup; exit "$status"; fi
    if [[ $CHANGED == 1 ]]; then
        # Capture evidence before disabling/removing the failed service units.
        # A volatile journal disappears on reboot on stock HaierPi devices.
        {
            echo "Diagnostic failure at $(date -u -Is), exit=$status"
            for unit in "${ALL_UNITS[@]}"; do
                echo "=== $unit STATUS ==="
                systemctl status "$unit.service" --no-pager -l 2>&1 || true
                echo "=== $unit JOURNAL ==="
                journalctl -b -u "$unit.service" --no-pager -l -n 150 2>&1 || true
            done
            echo "=== STORAGE ==="
            df -h / /opt
        } > "$SNAP/failure-diagnostics.log" 2>&1 || true
        chmod 600 "$SNAP/failure-diagnostics.log" 2>/dev/null || true
        echo "Failure evidence saved: $SNAP/failure-diagnostics.log" >&2
        echo "DIAGNOSTICS FAILED: restoring only PR6/PR7/PR8; original HaierPi untouched" >&2
        for unit in "${ALL_UNITS[@]}"; do
            systemctl stop "$unit.service" >/dev/null 2>&1 || true
            systemctl disable "$unit.service" >/dev/null 2>&1 || true
        done
        for x in "$APP" /opt/haierpi-pr6 /opt/haierpi-pr7 /opt/haierpi-pr8 \
                 /etc/haierpi-diagnostics.env \
                 /etc/haierpi-pr6.env /etc/haierpi-pr7.env /etc/haierpi-pr8.env \
                 /etc/systemd/system/haierpi-pr6.service \
                 /etc/systemd/system/haierpi-pr7.service \
                 /etc/systemd/system/haierpi-pr8.service \
                 /etc/systemd/system/haierpi-cycles.service \
                 /etc/systemd/system/haierpi-circuit.service; do
            rm -rf -- "$x"
        done
        # Restore data from snapshot (never discard current state without a verified backup).
        [[ ! -e "$DATA" ]] || rm -rf -- "$DATA"
        if ! tar -xzpf "$SNAP/previous.tar.gz" -C /; then
            echo "CRITICAL: diagnostics rollback incomplete; snapshot $SNAP" >&2
        fi
        systemctl daemon-reload || true
        for unit in "${ALL_UNITS[@]}"; do
            [[ ! -f "$SNAP/$unit.enabled" ]] || systemctl enable "$unit.service" || true
            [[ ! -f "$SNAP/$unit.active" ]] || systemctl start "$unit.service" || true
        done
    fi
    echo "Diagnostic backup retained: $SNAP" >&2
    cleanup
    exit "$status"
}
trap rollback ERR INT TERM
trap '[[ $READY == 1 ]] || rollback' EXIT

if id haierpi_diag >/dev/null 2>&1; then
    DIAG_USER=haierpi_diag
else
    useradd --system --no-create-home --shell /usr/sbin/nologin haierpi_diag
    DIAG_USER=haierpi_diag
fi
DIAG_GROUP="$(id -gn "$DIAG_USER")"

CHANGED=1
for unit in "${ALL_UNITS[@]}"; do systemctl stop "$unit.service" >/dev/null 2>&1 || true; done
# Explicitly retire the legacy SQLite writer and numeric-name units.
for unit in "${LEGACY_UNITS[@]}"; do
    systemctl disable "$unit.service" >/dev/null 2>&1 || true
    rm -f -- "/etc/systemd/system/$unit.service"
done
# One venv and one diagnostics tree; no core archive extraction and no core backup.
rm -rf -- "$APP"
install -d -o "$DIAG_USER" -g "$DIAG_GROUP" -m 750 "$APP"
cp -a "$STAGE/.venv" "$APP/.venv"
cp -a "$STAGE/code/diagnostics" "$APP/diagnostics"
chown -R "$DIAG_USER:$DIAG_GROUP" "$APP"
install -m 600 "$STAGE/mqtt.env" /etc/haierpi-diagnostics.env
for unit in "${UNITS[@]}"; do
    sed -e "s|^User=.*|User=$DIAG_USER|" \
        -e "s|^Group=.*|Group=$DIAG_GROUP|" \
        "$ROOT/deployment/$unit.service" > "/etc/systemd/system/$unit.service"
done
systemctl daemon-reload
for unit in "${UNITS[@]}"; do systemctl enable --now "$unit.service"; done
sleep "${HPI_CHECK_SECONDS:-15}"
systemctl is-active --quiet "$SERVICE" || err "Original controller stopped unexpectedly"
for unit in "${UNITS[@]}"; do systemctl is-active --quiet "$unit.service" || err "$unit inactive"; done
"$APP/.venv/bin/python" "$APP/diagnostics/install_verify.py" \
    --env /etc/haierpi-diagnostics.env --timeout "${HPI_VERIFY_SECONDS:-180}" --no-db

READY=1
trap - ERR INT TERM EXIT
cleanup
echo "SUCCESS: HaierPi cycle monitor and refrigeration circuit monitor online; SQLite historian retired; original HaierPi unchanged."
echo "Verified backup: $SNAP"
