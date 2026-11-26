# HaierPi 1.4.5_4 — Stable + GPIO/RS485 and MQTT reliability

Based on 1.4.5_3. Retains RAM-only diagnostics and HA heartbeat watchdog. Adds the independently reviewed GPIO/RS485 initialization and MQTT reconnect/PUBACK patches (upstream PRs #5 and #6). No new WWW changes; existing compatible local WWW changes are preserved, not distributed here. No change to heating settings or boot configuration. Original Stable archive is included unchanged for provenance, not automatically extracted over a live installation.

## Installation
On an existing compatible Stable 1.4.5 installation, verify the SHA256, extract, and run as root:

    bash install-1454.sh --dry-run
    bash install-1454.sh

Use --core-only to leave diagnostic sidecars untouched. Already patched core files are not restarted. The installer refuses read-only storage instead of changing mounts or boot configuration. GPIO.py comes from the installed device, not the Stable archive; unknown source layouts are rejected. A backup of changed files is printed and a failed core service startup triggers rollback. Diagnostic sidecar installation is a separate step; verify its result independently. Check fresh RS485 telemetry, MQTT heartbeat and service status after installation. Active service alone does not prove telemetry is healthy.

## Validation
Individual patches passed Python 3.9/3.11 CI, actual Paho/Mosquitto outage test and NanoPi service restart, broker outage/recovery and full reboot with persistent read-write storage. The combined release installer has separate CI checks; physical testing of the packaged installer remains pending. Stalled PUBACK with active TCP was simulated, not reproduced physically. No automatic release publication until combined CI is reviewed.

Upstream: https://github.com/kamilostatek/hpi/pull/5 and https://github.com/kamilostatek/hpi/pull/6
