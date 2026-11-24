# One-command deployment for HaierPi 1.4.5 alpha13 diagnostics

The entrypoint is **install-all-safe.sh**, NOT alpha13.sh.
It performs a transactional update of the original HaierPi and deploys
PR6 (cycle counters), PR7 (advanced circuit telemetry) and PR8 (SQLite).
The installer does not change any control/Modbus commands beyond the
source patches #1–#4, and the diagnostic modules only read MQTT.

## One-time prerequisites
- Original HaierPi installed at /opt/haier with /opt/config.ini and
  systemd service haier.service.
- Linux host with Python 3.10+ (for the independent diagnostic services),
  systemd, network access to install paho-mqtt and an MQTT broker.
- Retained Home Assistant MQTT Discovery configurations from HaierPi.
- MQTT broker host/credentials and HaierPi topic prefix must be known.
- MQTT credentials, port and topic prefix are **automatically read** from
  existing `/opt/config.ini` (sections `[MQTT]` and `[HOMEASSISTANT]`).
  No new MQTT configuration file is required.
- Existing HaierPi must already have MQTT and HA MQTT Discovery enabled.
  The installer will not enable either automatically or guess credentials.
  MQTT over TLS is not supported by these sidecars; installation safely
  stops before changing the running controller in that case.
- Confirm enough free disk for backup of entire /opt/haier tree and
  existing /var/lib/haierpi history database.

## Start
From inside the extracted archive:

```sh
sudo bash install-all-safe.sh
```

Do not invoke `alpha13.sh` directly; it has no transaction logic.

The unified script derives the MQTT configuration from HaierPi, checks the environment and installs Python dependencies
in a temporary directory **before touching the running controller**.
It backs up old diagnostic services/configuration, invokes install-safe.sh
to snapshot and update the core with the local pinned release archive,
then deploys/enables all three services under systemd. It checks the core
and each diagnostic service after startup.

On error, it stops all diagnostic services, restores previous
files/units/enabled + active state and persisted counter/history data,
then invokes rollback-safe.sh to restore the old core. Backups are under
`/var/backups/haierpi/integrated-<timestamp>`.

## Important limitations
- This is **still not verified on the actual heat pump**, broker and HA.
- An active systemd process alone does not prove correct MQTT values.
  Verify all new sensors are available and have sensible values after
  installation. If any source sensors are unavailable, don't infer
  that the device is working correctly just because the service is active.
- Python 3.10+ and required broker credentials must be available.
- This installer is designed for the stated file paths; inspect first
  if the original installation differs. Do not run blindly.
- Manual rollback can also be performed using core snapshots and the
  included rollback-safe.sh; a full diagnostic rollback is best performed
  using the installation transaction's automatic failure path.

## Tests
The ZIP is built only after the complete suite of unit tests, simulated
MQTT functional tests, integration tests and rollback smoke test passes.
Those tests do not substitute for live equipment validation.
