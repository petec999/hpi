# HaierPi alpha13 integrated diagnostics bundle — 24 November 2026

**Fork-only development snapshot.** Included: fixes #1–#4 plus read-only
compressor/defrost counters (#6), advanced circuit telemetry (#7), and
SQLite history/CSV export (#8). No upstream project modifications.

## TEST STATUS
All branch CI tests and simulated runtime tests must pass before this ZIP
is published by GitHub Actions. These are **offline/synthetic** checks.
There has been NO validation on the owner's actual pump, MQTT broker or
Home Assistant. The bundled services are only enabled when a deployment installer is explicitly run.

## Low-space HaierPi: diagnostics-only one-command deployment (recommended)

The real device has a **246 MB overlay root** and a separate /opt (only 43 MB
free on the last inspection). An earlier full installer filled overlayfs-root
with 150 MB + 96 MB backup snapshots, and rollback failed; it has been
restored manually and its critical rescue backup must NOT be deleted.

**Run `bash install-diagnostics-light.sh` from a pinned extracted bundle.**
This mode:
- installs PR6, PR7, PR8 only; **does not patch or reinstall core fixes #1–#4**;
- refuses to proceed unless the current HaierPi is active and already
  publishes freshness signals required by PR6/PR7;
- uses ONE shared /opt/haierpi-diagnostics/.venv rather than three venvs;
- checks free space on both filesystems before changing any service;
- backs up only pre-existing diagnostic files, data and systemd units;
- derives broker settings automatically from /opt/config.ini;
- verifies MQTT online and SQLite with automatic diagnostics-only rollback;
- preserves the independent /opt/haier application and config unchanged.

Do NOT delete /opt/haierpi-rescue or the original backups to run this.

## Full core + diagnostics deployment — fail-closed low-space guard

**Use `install-all-safe.sh` only on hosts with sufficient filesystem capacity.** It snapshots
the existing core installation, configuration, diagnostic services and
persistent data; installs the pinned alpha13 #1–#4 fixes and all three
PR6/PR7/PR8 systemd services; checks whether they remain active; and
attempts a combined rollback if a stage fails. It automatically reads MQTT broker settings and credentials from the
existing `/opt/config.ini`, and writes a protected (0600) temporary
configuration for all three diagnostic services. No separate manual
MQTT setup is needed when HaierPi already has MQTT and MQTT Discovery
enabled with non-TLS transport. It refuses disabled MQTT/Discovery or
unsupported TLS rather than changing the controller settings.
See `docs/UNIFIED_SAFE_INSTALL.md` for prerequisites and limitations.

**On this small HaierPi use the light installer, not the full one.** The full installer now checks space BEFORE changing the core and refuses unsafe upgrades.

An optional explicit `HPI_DIAGNOSTICS_ENV` can override autodetection,
but the default is zero additional MQTT configuration.

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
Each service needs Python 3.9+, `paho-mqtt`, a working Mosquitto broker,
retained MQTT Discovery source definitions and valid MQTT credentials.
The unified installer reads real topic prefixes and broker credentials
from existing HaierPi config. Standalone manual deployment instead requires
configuration of the respective env files.

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

## Home Assistant dashboard and PR8 reporting (no reinstall)

The build includes **HaierPi-HA-dashboard-PR6-PR7-PR8.zip** as a
separate tiny artifact, containing:
- `homeassistant/haier-diagnostyka-view.yaml` — a Lovelace view
  using all **8 confirmed PR6** and **6 confirmed PR7** entities, with
  a Polish summary, minutes/hours conversion and history graphs.
- `tools/pr8_report.py` — read-only standard-library SQLite history
  summary and optional CSV export.

To add the panel, open the existing HA dashboard, create a new view and
choose the raw YAML editor for that **view**. Paste the contents of
`haier-diagnostyka-view.yaml`. This is a view snippet, NOT the complete
dashboard configuration, and needs no additional HA frontend plugins.
Do not replace the entire dashboard with this snippet.

PR8 is already running separately and logging to
`/var/lib/haierpi/history.sqlite`. It does not create HA entities.
On HaierPi after downloading the single script, a safe check is:

```sh
python3 pr8_report.py
```

Optional CSV exports:
```sh
python3 pr8_report.py --samples-csv /tmp/haier-samples.csv --events-csv /tmp/haier-events.csv
```

The script opens SQLite read-only and refuses to overwrite existing CSV
files. The PR8 historian prunes samples/events older than 90 days by
default, but its database and WAL can still grow: monitor free space on
the filesystem hosting `/var/lib/haierpi`. The HA history graphs query
Home Assistant's recorder, not PR8 SQLite.

## Deployment prerequisites
1. Back up the original HaierPi installation, config and service unit.
2. Capture actual MQTT Discovery messages and pump data formats.
3. Verify source topic mapping and defrost flag semantics against live data.
4. Stage testing outside the working controller.
5. Check service permissions, MQTT connections and recovery on restart.
6. Only then consider production deployment, with documented rollback.

No equipment is modified by downloading or extracting this ZIP.
