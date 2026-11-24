#!/usr/bin/env bash
# One-command transactional deployment: HaierPi #1-4 plus PR6/7/8.
# Requires a prepared /etc/haierpi-diagnostics.env; never guesses MQTT secrets.
set -Eeuo pipefail
umask 077
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE="${HPI_SERVICE:-haier}"
STORE="${HPI_DATA_DIR:-/var/lib/haierpi}"
BACKUP_ROOT="${HPI_BACKUP_ROOT:-/var/backups/haierpi}"
MQTT_ENV="${HPI_DIAGNOSTICS_ENV:-}"
HPI_EXISTING_CONFIG="${HPI_CONFIG:-/opt/config.ini}"
PYTHON="${HPI_PYTHON:-python3}"
CHECK_SECONDS="${HPI_CHECK_SECONDS:-15}"
CORE_SCRIPT="$ROOT/install-safe.sh"
RESTORE_CORE="$ROOT/rollback-safe.sh"
SNAP=""
DONE=0
CORE_DONE=0

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
[[ "$EUID" == 0 ]] || fail "Run with sudo/root"
# MQTT broker settings are discovered automatically from existing HaierPi.
# An explicit HPI_DIAGNOSTICS_ENV remains an optional override.
if [[ -n "$MQTT_ENV" ]]; then
    [[ -f "$MQTT_ENV" && -s "$MQTT_ENV" ]] || fail "Explicit MQTT env file is missing"
    [[ "$(stat -c '%a' "$MQTT_ENV")" == 600 ]] || fail "Explicit MQTT env must have permissions 600"
fi
[[ "$CHECK_SECONDS" =~ ^[0-9]+$ ]] || fail "Bad check time"
for bin in systemctl tar "$PYTHON" cp mv sed flock stat; do command -v "$bin" >/dev/null || fail "Missing $bin"; done
if id haier >/dev/null 2>&1; then
    DIAG_USER=haier
elif id nobody >/dev/null 2>&1; then
    DIAG_USER=nobody
else
    fail "No non-privileged account for diagnostic services"
fi
DIAG_GROUP="$(id -gn "$DIAG_USER")"
for file in "$CORE_SCRIPT" "$RESTORE_CORE" "$ROOT/alpha13.sh" "$ROOT/1.4.5_alpha13.tar.gz"; do
    [[ -f "$file" ]] || fail "Missing $file"
done
for n in 6 7 8; do
    [[ -f "$ROOT/deployment/haierpi-pr$n.service" ]] || fail "Missing PR$n service unit"
done
# Validate network and venv capability before touching the existing controller.
"$PYTHON" - <<'PY'
import sys, venv
assert sys.version_info >= (3,10), 'Python 3.10+ is required for diagnostics'
PY
# Optional override config is checked before touching the controller.
# Do not source secrets into the installer's own shell.
if [[ -n "$MQTT_ENV" && -f "$MQTT_ENV" ]]; then
"$PYTHON" - "$MQTT_ENV" <<'PY'
import sys, re
keys={"HPI_MQTT_HOST","HPI_MQTT_PORT","HPI_MQTT_USERNAME",
      "HPI_MQTT_PASSWORD","HPI_TOPIC","HPI_DISCOVERY_PREFIX",
      "HPI_TZ","HPI_SAMPLE_TTL","HPI_HISTORY_RETENTION_DAYS"}
data={}
for line in open(sys.argv[1],encoding="utf-8"):
    t=line.strip()
    if not t or t.startswith("#"): continue
    if "=" not in t: raise SystemExit("Invalid MQTT env entry")
    k,v=t.split("=",1)
    if not re.fullmatch(r"[A-Z_0-9]+",k) or k not in keys:
        raise SystemExit("Unsupported MQTT env key: "+k)
    if "\n" in v or "\r" in v: raise SystemExit("Bad value")
    data[k]=v.strip().strip('"')
if not data.get("HPI_MQTT_HOST"): raise SystemExit("Set HPI_MQTT_HOST")
if not data.get("HPI_TOPIC"): raise SystemExit("Set HPI_TOPIC")
PY
fi

# All dependencies prepared in staging first. Failure here leaves original untouched.
STAGING="$(mktemp -d /tmp/haierpi-stage.XXXXXXXX)"
cleanup_stage(){ rm -rf -- "$STAGING"; }
trap cleanup_stage EXIT
if [[ -z "$MQTT_ENV" ]]; then
    MQTT_ENV="$STAGING/diagnostics.env"
    "$PYTHON" "$ROOT/diagnostics/derive_mqtt_env.py" \
        --config "$HPI_EXISTING_CONFIG" --output "$MQTT_ENV" ||
        fail "Cannot automatically read existing MQTT settings; original installation unchanged"
fi
[[ "$(stat -c '%a' "$MQTT_ENV")" == 600 ]] || fail "MQTT config must have permissions 600"
"$PYTHON" -m venv "$STAGING/venv"
"$STAGING/venv/bin/python" -m pip install --disable-pip-version-check 'paho-mqtt>=1.6,<3'
"$STAGING/venv/bin/python" -c 'import paho.mqtt.client' || fail "paho-mqtt unavailable"

mkdir -p "$BACKUP_ROOT"
exec 8>"$BACKUP_ROOT/.integrated.lock"
flock -n 8 || fail "Integrated installer already running"
SNAP="$BACKUP_ROOT/integrated-$(date -u +%Y%m%dT%H%M%SZ)-$$"
mkdir -m 700 "$SNAP"
mkdir -p "$SNAP/old"
# Save previous service state and every path which will be created/replaced.
for n in 6 7 8; do
    key="haierpi-pr$n"
    path="/opt/$key"
    unit="/etc/systemd/system/$key.service"
    envpath="/etc/$key.env"
    for name in "$path" "$unit" "$envpath"; do
        tag="$(echo "$name" | tr '/' '_')"
        if [[ -e "$name" || -L "$name" ]]; then
            tar -cpf "$SNAP/old/$tag.tar" -C / "${name#/}"
        else
            touch "$SNAP/old/$tag.absent"
        fi
    done
    systemctl is-enabled --quiet "$key.service" && touch "$SNAP/old/$key.enabled" || true
    systemctl is-active --quiet "$key.service" && touch "$SNAP/old/$key.active" || true
done
if [[ -e "$STORE" ]]; then
    tar -cpf "$SNAP/old/data.tar" -C / "${STORE#/}"
else
    touch "$SNAP/old/data.absent"
fi
# Every file is snapshotted before installing core or sidecars.
rollback_all() {
    local rc="$1"
    trap - ERR INT TERM EXIT
    [[ "$DONE" == 1 ]] && exit "$rc"
    echo "INTEGRATED INSTALL FAILED: restoring previous application/services" >&2
    for n in 6 7 8; do systemctl stop "haierpi-pr$n.service" || true; systemctl disable "haierpi-pr$n.service" || true; done
    for n in 6 7 8; do
        key="haierpi-pr$n"
        for name in "/opt/$key" "/etc/systemd/system/$key.service" "/etc/$key.env"; do
            tag="$(echo "$name" | tr '/' '_')"
            rm -rf -- "$name"
            [[ -f "$SNAP/old/$tag.tar" ]] && tar -xpf "$SNAP/old/$tag.tar" -C / || true
        done
    done
    if [[ -f "$SNAP/old/data.tar" ]]; then
        rm -rf -- "$STORE"
        tar -xpf "$SNAP/old/data.tar" -C / || echo "WARNING: data restore failed" >&2
    elif [[ -f "$SNAP/old/data.absent" ]]; then
        rm -rf -- "$STORE"
    fi
    systemctl daemon-reload || true
    for n in 6 7 8; do
        key="haierpi-pr$n"
        if [[ -f "$SNAP/old/$key.enabled" ]]; then systemctl enable "$key.service" || true; fi
        if [[ -f "$SNAP/old/$key.active" ]]; then systemctl start "$key.service" || true; fi
    done
    if [[ "$CORE_DONE" == 1 && -f "$SNAP/core-snapshot-path" ]]; then
        bash "$RESTORE_CORE" "$(cat "$SNAP/core-snapshot-path")" ||
            echo "CRITICAL: core rollback needs manual attention" >&2
    fi
    echo "Rollback backup preserved: $SNAP" >&2
    exit "$rc"
}
trap 'rollback_all "$?"' ERR INT TERM
# EXIT must cover explicit exits too, but the stage cleanup remains in rollback.
trap 'rc=$?; if [[ "$DONE" != 1 ]]; then rollback_all "$rc"; fi; cleanup_stage' EXIT

echo "Backing up core HaierPi and installing pinned release..."
CORE_BACKUPS="$SNAP/core"
mkdir -m 700 "$CORE_BACKUPS"
HPI_BACKUP_ROOT="$CORE_BACKUPS" HPI_CHECK_SECONDS="$CHECK_SECONDS" bash "$CORE_SCRIPT"
CORE_SNAP="$(find "$CORE_BACKUPS" -mindepth 1 -maxdepth 1 -type d -print -quit)"
[[ -n "$CORE_SNAP" ]] || fail "Core snapshot missing"
printf '%s\n' "$CORE_SNAP" > "$SNAP/core-snapshot-path"
CORE_DONE=1

# Deploy three isolated services; never overwrite controller files.
install -d -o "$DIAG_USER" -g "$DIAG_GROUP" -m 750 "$STORE"
for n in 6 7 8; do
    key="haierpi-pr$n"
    systemctl stop "$key.service" >/dev/null 2>&1 || true
    rm -rf -- "/opt/$key"
    mkdir -p "/opt/$key"
    cp -a "$ROOT/diagnostics" "/opt/$key/"
    cp -a "$STAGING/venv" "/opt/$key/.venv"
    chown -R "$DIAG_USER:$DIAG_GROUP" "/opt/$key"
    install -m 644 "$ROOT/deployment/$key.service" "/etc/systemd/system/$key.service"
    sed -i "s/^User=.*/User=$DIAG_USER/; s/^Group=.*/Group=$DIAG_GROUP/" "/etc/systemd/system/$key.service"
    install -m 600 "$MQTT_ENV" "/etc/$key.env"
done
systemctl daemon-reload
for n in 6 7 8; do
    systemctl enable --now "haierpi-pr$n.service"
done
sleep "$CHECK_SECONDS"
systemctl is-active --quiet "$SERVICE" || fail "Core HaierPi is not active"
for n in 6 7 8; do
    systemctl is-active --quiet "haierpi-pr$n.service" || fail "PR$n failed health check"
done
# Systemd active is not sufficient. Require actual MQTT Discovery health from
# PR6/PR7 and SQLite initialization in PR8, or roll back this deployment.
"$STAGING/venv/bin/python" "$ROOT/diagnostics/install_verify.py" \
    --env "$MQTT_ENV" --timeout "${HPI_VERIFY_SECONDS:-180}" || \
    fail "Integrated MQTT/SQLite check failed"
DONE=1
echo "SUCCESS: Core + PR6 + PR7 + PR8 active. Backup: $SNAP"
echo "Note: active processes are not proof of live MQTT sensor values; verify HA availability."
