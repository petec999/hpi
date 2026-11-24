# HaierPi alpha13 integrated diagnostics bundle — 24 November 2026

**Fork-only development snapshot.** Included: fixes #1–#4 plus read-only
compressor/defrost counters (#6), advanced circuit telemetry (#7), and
SQLite history/CSV export (#8). No upstream project modifications.

## TEST STATUS
All branch CI tests and simulated runtime tests must pass before this ZIP
is published by GitHub Actions. These are **offline/synthetic** checks.
There has been NO validation on the owner's actual pump, MQTT broker or
Home Assistant. The bundled services are **not automatically enabled**.

## Unified automatic deployment
**Use `install-all-safe.sh` as the primary entrypoint.** It snapshots
the existing core installation, configuration, diagnostic services and
persistent data; installs the pinned alpha13 #1–#4 fixes and all three
PR6/PR7/PR8 systemd services; checks whether they remain active; and
attempts a combined rollback if a stage fails. It needs an existing
`/etc/haierpi-diagnostics.env` containing MQTT broker details with
permissions 600. Create it from
`deployment/haierpi-diagnostics.env.example` first.
See `docs/UNIFIED_SAFE_INSTALL.md` for prerequisites and limitations.

**Run `sudo bash install-all-safe.sh`, not `alpha13.sh`.**

The narrower `install-safe.sh` script remains available for a core-only
upgrade but does not deploy diagnostic services.

## SAFE installation and rollback
The raw `alpha13.sh` **is not the production entry point**: it stops the
service and changes installed files. The included `install-safe.sh` wrapper:
- verifies the local pinned `1.4.5_alpha13.tar.gz` before stopping service;
- backs up the entire current app tree (including PyHaier), config and
  service-unit text into a dated private snapshot in /var/backups/haierpi;
- starts the bundled alpha13 installer with the pinned local archive;
- checks the service is running after a configurable monitoring interval;
- automatically stops and restores the full snapshot/config after failure,
  then starts the previous service if it was previously running.
A separate `rollback-safe.sh <snapshot-directory>` restores manually.
Run `sudo bash install-safe.sh` from the extracted bundle **only after**
verifying the service layout, permissions and MQTT dependencies. The defaults
expect the same Linux paths as the existing HaierPi installation.

The all-in-one wrapper installs PR6–PR8 together with the core. The older
install-safe.sh only handles the core. Verify on staged hardware first.

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
