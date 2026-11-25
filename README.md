# HaierPi — Stable 1.4.5 + RAM diagnostics + MQTT watchdog

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
