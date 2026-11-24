# HaierPi alpha13 integrated diagnostics bundle — 24 November 2026

**Fork-only development snapshot.** Included: fixes #1–#4 plus read-only
compressor/defrost counters (#6), advanced circuit telemetry (#7), and
SQLite history/CSV export (#8). No upstream project modifications.

## TEST STATUS
All branch CI tests and simulated runtime tests must pass before this ZIP
is published by GitHub Actions. These are **offline/synthetic** checks.
There has been NO validation on the owner's actual pump, MQTT broker or
Home Assistant. The bundled services are **not automatically enabled**.

## IMPORTANT: DO NOT RUN alpha13.sh DIRECTLY ON THE WORKING PUMP
The inherited alpha13 installer stops the running service and removes
installed files before unpacking. The script also downloads the archive
from the upstream main branch rather than using the included copy.
Review and change this behavior before real deployment. This bundle
is for inspection and staged deployment preparation, **not** a
one-click production installer.

## Bundle structure
- `1.4.5_alpha13.tar.gz`: original upstream alpha13 archive, unchanged
- `alpha13.sh`: combined source patches for fixes #1–#4, inherited installer
- `diagnostics/`: three independent Python read-only sidecar applications
- `deployment/`: example systemd units and environment files
- `tests/`: regression and simulated end-to-end checks
- `tools/`: alpha13 patch tools
- `docs/`: source-level explanations and individual feature requirements

## Sidecar services
Each service needs Python 3.10+, `paho-mqtt`, a working Mosquitto broker,
retained MQTT Discovery source definitions and valid MQTT credentials.
Set real topic prefixes before starting. Copy sources into a dedicated
directory and configure the service users/permissions for your system.

- PR6: `python -m diagnostics.mqtt_cycle_bridge`
- PR7: `python -m diagnostics.mqtt_circuit_bridge`
- PR8: `python -m diagnostics.mqtt_history`

The PR6/PR7 services require R141/R241 freshness topics from fix #4.
The compressor frequency source must use the corrected mapping from
fix #2.

## Persistence
- PR6: `/var/lib/haierpi/cycle_counters.json`
- PR8: `/var/lib/haierpi/history.sqlite` and SQLite WAL side files

Back up these files, ensure writable directory ownership, and do not
place persistent data under /opt/haier (the inherited installer removes
some of its contents).

## Metrics exported to Home Assistant
- PR6: 8 daily compressor/defrost counter sensors via MQTT Discovery
- PR7: 6 derived refrigerant/hydraulic diagnostic sensors via MQTT Discovery
- PR8: SQLite telemetry historian and CSV/summary CLI (no dashboard)

## Deployment prerequisites
1. Back up the original HaierPi installation, config and service unit.
2. Capture actual MQTT Discovery messages and pump data formats.
3. Verify source topic mapping and defrost flag semantics against live data.
4. Stage testing outside the working controller.
5. Check service permissions, MQTT connections and recovery on restart.
6. Only then consider production deployment, with documented rollback.

No equipment is modified by downloading or extracting this ZIP.
