# Compressor and defrost cycle monitoring (RAM-only)

The read-only service is **`haierpi-cycles.service`**, running
`diagnostics/mqtt_cycle_bridge.py` on NanoPi.

It learns compressor frequency and defrost state from retained HaierPi MQTT
Discovery configuration; raw source readings must be **live**, not retained.
R141/R241 and connection availability are checked before producing usable data.

## Exported sensors

- Compressor starts today
- Compressor running seconds today
- Completed compressor cycles today
- Last completed compressor cycle duration (seconds)
- Defrost starts today
- Defrost running seconds today
- Completed defrost cycles today
- Last completed defrost duration (seconds)

MQTT state topics remain under `<HPI_TOPIC>/diagnostics/counters/`.
The historical MQTT `unique_id` prefix `HaierPi_PR6_` is intentionally kept
**only for Home Assistant entity continuity**; it is *not* the systemd name.

## No card writes

The live service creates `CycleCounter()` **without a file path**.
Counters reside entirely in process memory; no JSON files are created, and
there is no SQLite recorder. Today's counts reset if the service restarts
or the NanoPi reboots. Store longer-term series in Home Assistant instead.

Run with `install-diagnostics-light.sh`, not a legacy numeric-name unit.
OverlayFS autostart is documented in `docs/OVERLAYFS_AUTOSTART.md`.

Intervals across telemetry gaps are not invented or backfilled. A fresh
sample after restart or a gap initializes the baseline without counting
a false new compressor start.

## Tests

```sh
python3 -m unittest discover -s tests -p 'test_cycle_counter_pr6.py' -v
python3 -m unittest discover -s tests -p 'test_pr6_runtime_simulation.py' -v
```
