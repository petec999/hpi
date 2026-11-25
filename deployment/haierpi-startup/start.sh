#!/bin/bash
# Restore RAM-backed systemd diagnostic configuration on OverlayFS HaierPi.
# This is intentionally a one-shot boot script, NOT a data logger.
set -Eeuo pipefail

APP=/opt/haierpi-diagnostics
BOOT=/opt/haierpi-startup

echo "HaierPi diagnostics: restoring RAM configuration"

# Application and templates are permanently installed on /opt.
[ -x "$APP/.venv/bin/python" ] || exit 1
[ -f "$APP/diagnostics/derive_mqtt_env.py" ] || exit 1
[ -f /opt/config.ini ] || exit 1

# Preserve the UID/GID owning the existing /opt files.
if getent group haierpi_diag >/dev/null; then
    [ "$(getent group haierpi_diag | cut -d: -f3)" = 998 ] || exit 1
else
    if getent group 998 >/dev/null; then exit 1; fi
    groupadd --system --gid 998 haierpi_diag
fi

if id haierpi_diag >/dev/null 2>&1; then
    [ "$(id -u haierpi_diag)" = 998 ] || exit 1
    [ "$(id -g haierpi_diag)" = 998 ] || exit 1
else
    if getent passwd 998 >/dev/null; then exit 1; fi
    useradd --system --uid 998 --gid 998 \
        --no-create-home --home-dir /nonexistent \
        --shell /usr/sbin/nologin haierpi_diag
fi

# MQTT password is read from /opt/config.ini into OverlayFS RAM, not /boot.
python3 "$APP/diagnostics/derive_mqtt_env.py" \
    --config /opt/config.ini \
    --output /etc/haierpi-diagnostics.env

for unit in haierpi-cycles haierpi-circuit; do
    install -o root -g root -m 644 \
        "$BOOT/$unit.service" \
        "/etc/systemd/system/$unit.service"
done

systemctl daemon-reload
systemctl enable --now haierpi-cycles.service haierpi-circuit.service
echo "HaierPi diagnostics: startup completed"
