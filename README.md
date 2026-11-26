# HaierPi Android companion

**Current preview: 0.2.0** — native Android dashboard, Adaptive/experiment readings, session charts, confirmed basic controls and offline demo. Requires a compatible HaierPi v2 API for live use. No pump firmware changes.

[Download APK ZIP from successful CI (GitHub login required)](https://github.com/petec999/hpi/actions/runs/45868217263) · [Installation, build and limitations](android-app/README.md) · [Current Adaptive server](https://github.com/petec999/hpi/tree/feature/adaptive-learning)

The Android branch is independent of the live Adaptive branch. Its inherited server sources are a historical baseline, **not** the current recommended controller installer.

## Test checklist

- Install on Android 8+; uninstall the old preview if its signing key differs.
- Open demo, check all four tabs and rotation.
- Connect to the real host, log in through WWW, return to the native dashboard, confirm live JSON.
- Test disconnection/session expiry: no writes on missing/stale state.
- Verify confirmed controls against actual server readback; never test disruptive operations solely for UI verification.
- Pending before Play: stable signing, AAB, current target API review, privacy/data-safety disclosure, store graphics and device tests. No production release or Play submission yet.

## Historical inherited server README

Current distribution: **[1.4.5_3 (prerelease)](https://github.com/petec999/hpi/releases/tag/v1.4.5_3)**. This branch contains the complete installation sources, not a replacement for upstream Stable 1.4.5.

## Quick update on an existing compatible HaierPi

Run on NanoPi as root. For existing diagnostics, install only the watchdog:

```bash
cd /tmp
BASE=https://github.com/petec999/hpi/releases/download/v1.4.5_3
curl -fsSLO "$BASE/1.4.5_3.tar.gz" &&
curl -fsSLO "$BASE/1.4.5_3.sha256" &&
sha256sum -c 1.4.5_3.sha256 &&
tar -xzf 1.4.5_3.tar.gz &&
cd HaierPi-1.4.5_3 &&
bash install-1453.sh --dry-run &&
bash install-1453.sh --watchdog-only
```

For a compatible core without the two RAM diagnostic services, use `bash install-1453.sh` instead. This is not a full core upgrade. The installer creates backups and preserves the initial mount flags, including RW if already writable.

Verify:
```bash
grep -n 'HOME-IOT MQTT WATCHDOG' /opt/haier/main.py
journalctl -u haier -b --no-pager | grep -i watchdog
systemctl is-active haier
```

## Validation, 25 November 2026

```text
# HOME-IOT MQTT WATCHDOG v2
14:00:00 MQTT watchdog OK: HA confirmed heartbeat (failures=0 recoveries=0)
active
```

[CI build and simulated failure/recovery tests](https://github.com/petec999/hpi/actions/runs/45618747904) passed. Hardware installation and normal HA round-trip are confirmed. Actual outage/reconnect, persistent notification and reboot tests remain open; automatic RO remount was not tested because /opt was already RW. Do not interrupt a working heating system solely to test these paths.

## Documentation

- [Release notes and architecture](RELEASE_1.4.5_3.md)
- [MQTT watchdog, prerequisites and rollback](docs/MQTT_END_TO_END_WATCHDOG.md)
- [OverlayFS startup](docs/OVERLAYFS_AUTOSTART.md)
- [Home Assistant dashboard setup](https://github.com/petec999/home-iot-telemetry/blob/main/home_assistant/README.md)

Published archives and tags are immutable; later README updates do not modify the released archive or its checksum.
