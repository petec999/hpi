# PR #8 — SQLite diagnostic history and CSV exports

This PR is a **read-only MQTT sidecar** for **petec999/hpi**. It stores
numeric sensor readings and selected diagnostic state transitions to a
persistent SQLite database, and offers CSV export and a summary command.
It never writes to Haier's Modbus registers, nor to its control MQTT topics.

## What is stored

- HaierPi numeric MQTT sensors discovered via retained Home Assistant
  MQTT Discovery configurations (`HaierPi_*` unique IDs, source topics
  restricted to the configured HaierPi topic prefix).
- PR6 daily counters and PR7 derived diagnostics, when their respective
  sidecars publish discovery configurations and fresh readings.
- A bounded set of diagnostic state transitions: `HaierPi_Defrost`,
  `HaierPi_Pump`, `HaierPi_3wayvalve`, `HaierPi_R141Fresh`,
  `HaierPi_R241Fresh`, and known error flags.

Changes are recorded on fresh non-retained MQTT updates. During startup,
retained MQTT values are **not** treated as historical observations. For
events the first fresh state is a baseline and does not create an event.
After a disconnect or restart, a new baseline is established.

Numeric recording is capped to one sample per sensor per 60 seconds by
default. Each reading has a UTC ISO timestamp and optional unit. The
default storage location is `/var/lib/haierpi/history.sqlite` (WAL mode).
Existing records survive process and device restarts when the configured
directory is persistent. The DB is outside the original alpha13 release
folders and should be included in backups.

Default retention is 90 days, checked hourly; change with
`HPI_HISTORY_RETENTION_DAYS`. It prunes both samples and events.

## Installation (manual; separate service)

Prerequisites: MQTT broker, HaierPi MQTT Discovery, Python 3.10+,
`paho-mqtt`. Example for a dedicated user named `haier`:

```sh
sudo mkdir -p /opt/haierpi-pr8 /var/lib/haierpi
sudo chown haier:haier /var/lib/haierpi
# Copy the repository's diagnostics/ module into /opt/haierpi-pr8/
cd /opt/haierpi-pr8
python3 -m venv .venv
.venv/bin/pip install paho-mqtt
sudo cp deployment/haierpi-pr8.service /etc/systemd/system/
sudo cp deployment/haierpi-pr8.env.example /etc/haierpi-pr8.env
sudo chmod 600 /etc/haierpi-pr8.env
# Set MQTT credentials and topics in /etc/haierpi-pr8.env
sudo systemctl daemon-reload
sudo systemctl enable --now haierpi-pr8.service
```

These commands are a template: copy both `diagnostics/` and
`deployment/` from the chosen PR8 branch before running them. The
service is intentionally not started by the existing alpha13 installer.

## Reports and CSV

```sh
cd /opt/haierpi-pr8
HPI_HISTORY_FILE=/var/lib/haierpi/history.sqlite .venv/bin/python -m diagnostics.mqtt_history --summary
HPI_HISTORY_FILE=/var/lib/haierpi/history.sqlite .venv/bin/python -m diagnostics.mqtt_history --export samples --output /tmp/haier_samples.csv
HPI_HISTORY_FILE=/var/lib/haierpi/history.sqlite .venv/bin/python -m diagnostics.mqtt_history --export events --output /tmp/haier_events.csv
```

CSV includes column headers. No dashboard or scheduled email reports are
implemented. Raw RS485 frame logging is intentionally **out of scope**.
There is no automatic backfill of prior history.

## Safety / known limits

- These are observations, not guaranteed manufacturer diagnostic records.
- MQTT-discovered numeric sensors using complex Jinja templates that cannot
  be reduced to a simple numeric value/JSON index are skipped.
- If HaierPi Discovery is not retained, the recorder cannot discover sources.
- MQTT retained values are ignored to avoid replaying stale measurements.
- A lost MQTT connection creates gaps; it cannot reconstruct missing time.
- The DB can grow; choose appropriate retention, backup, and disk space.
- On some installations the `haier` account may not exist; adjust the unit
  user/group and permissions before enabling it.
- No on-device integration test has yet been performed.

## Tests

```sh
python3 -m unittest discover -s tests -p 'test_history_pr8.py' -v
```
