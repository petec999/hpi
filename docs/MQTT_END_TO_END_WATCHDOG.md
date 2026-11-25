# MQTT end-to-end watchdog

HaierPi publishes a unique, non-retained heartbeat after each scheduled MQTT snapshot and checks the actual value reported by Home Assistant's REST API. It uses the existing HOMEASSISTANT HAADDR, HAPORT and KEY and MQTT discovery configuration in /opt/config.ini. No additional token or dependency is installed. Use a trusted local HA endpoint; the token is never included in the logs.

With snapshot_interval_s=30, warning follows 90 seconds without confirmation, alarm follows 180 seconds. Recovery is logged automatically. Counters are per process and RAM-only. A separate worker with bounded HTTP timeouts and single-flight locking avoids blocking the scheduler. The existing MQTT reconnect worker remains responsible for broker reconnection. V2 may request a single disconnect in that worker after at least three consecutive HTTP 200 heartbeat mismatches and 180 seconds without a confirmed heartbeat, only after a previously successful readback. Requests are limited to once per 900 seconds. No reconnect on API errors, 404, authentication failures, or disconnected broker.

Entity: sensor.haierpi_mqtt_heartbeat (the default entity ID must not be renamed; HTTP 404 can mean discovery is delayed or entity ID differs). The heartbeat confirms MQTT -> HA -> REST readback, not receipt of every individual telemetry topic or the freshness of Modbus frames. Existing R141/R241 freshness signals continue to cover pump reads. Heartbeat becomes unavailable after four snapshot periods (minimum 120 seconds).

Prerequisites: compatible core with MQTT enabled, snapshot_interval_s > 0, HA MQTT Discovery enabled, valid REST API token. If disabled, no heartbeat is emitted; no new pump control commands are sent.

## Installation

From the unpacked HaierPi-1.4.5_3 directory on HaierPi:
- `bash install-1453.sh --dry-run` validates patch anchors and Python syntax without modifying files.
- `bash install-1453.sh --watchdog-only` adds watchdog to an existing compatible core and preserves working diagnostic services.
- `bash install-1453.sh` installs both RAM diagnostics and watchdog on an existing compatible core. Existing diagnostics installer has its own rollback; installation of both components is not one atomic transaction.

The wrapper handles the observed F2FS /mnt, /ro and /opt bind layout, preserves original mount flags and refuses unknown RO layouts or detected storage errors. It takes a persistent source backup before changing main.py and rolls back if restart fails. It does not install the upstream core, modify fstab, or edit the existing overlay boot hook. Upstream upgrades can overwrite main.py; reapply the watchdog after a compatible core upgrade.

Check `journalctl -u haier -f | grep --line-buffered -iE 'mqtt|watchdog'`. Expected: MQTT watchdog OK: HA confirmed heartbeat. If the heartbeat is not confirmed, inspect API configuration and the actual entity ID first. No controller restart is performed by the running watchdog. At alarm level it also requests a persistent notification through HA REST API; after verified recovery it dismisses it. If HA API is down, the notification cannot be delivered until HA is reachable and the fault still persists. The existing v1 is upgraded in place.

Rollback: use the printed .main-before-1453.* backup, on a temporarily writable /opt, then restore RO flags and restart haier. The underlying original stable tarball is unchanged.

Validation: package build tests compatibility and syntax against official stable; hardware runtime and RO remount path require a live test. This is a prerelease.
