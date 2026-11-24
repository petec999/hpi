# PR #6 — compressor and defrost daily counters (MQTT integrated)

## Architecture

A read-only, standalone sidecar at `diagnostics/mqtt_cycle_bridge.py`
uses HaierPi's retained Home Assistant MQTT Discovery configuration to
find **actual frequency** (`HaierPi_Compfact`) and the explicit
**defrost** binary sensor (`HaierPi_Defrost`). MQTT source topics are
learned from Discovery rather than hard-coded. The Hz sensor must have
the correct compressor actual/target mapping (fix #2); R141/R241
freshness requires fix #4.

The sidecar subscribes to those source topics and three existing
availability topics. It rejects cached retained source measurements;
only new live messages are used. If input is missing or stale, its
eight sensors become unavailable and the counter does not invent work
or start events.

## Eight Home Assistant sensors (automatically via MQTT Discovery)

- Compressor starts today
- Compressor running seconds today
- Completed compressor cycles today
- Last completed compressor cycle duration (seconds)
- Defrost starts today
- Defrost running seconds today
- Completed defrost cycles today
- Last completed defrost duration (seconds)

Discovery IDs use `HaierPi_PR6_`. The sidecar's telemetry is published
under `<HPI_TOPIC>/diagnostics/counters/`, separate from native control topics.
No user YAML is needed when MQTT Discovery is enabled.

## Persistence and restart

Counters live in versioned atomic JSON under
`/var/lib/haierpi/cycle_counters.json` by default, outside alpha13
installation files. Daily counts survive process and device restarts
as long as this data directory survives. A restart resets the
current observed ON/OFF baseline (avoids false starts). Only the
current day is retained in the JSON. Older historical readings
can be preserved by PR #8's SQLite recorder.

At midnight, a new daily set begins on the next observation. Intervals
crossing midnight are not split and cannot be reconstructed. Time totals
are conservatively estimated from confirmed consecutive ON readings;
a transition interval itself is not credited. Samples missed during
communication outages are not backfilled.

## Running as a separate service

The service template is `deployment/haierpi-pr6.service` and its
environment configuration is `deployment/haierpi-pr6.env.example`.
It needs Python 3.10+, `paho-mqtt`, a writable
`/var/lib/haierpi` and MQTT access. It is **not** automatically
installed by `alpha13.sh` and does **not** modify HaierPi or heat pump
control logic. To enable, install the branch's `diagnostics/` folder
and the service unit into a dedicated deployment directory, set the
broker host/credentials and the actual MQTT topic prefix, then enable
the service with systemd. Verify HaierPi Discovery topics on the
real broker before enabling.

## Validation

```sh
python3 -m unittest discover -s tests -p test_cycle_counter_pr6.py -v
python3 -m unittest discover -s tests -p test_pr6_runtime_simulation.py -v
```

The simulated end-to-end test exercises MQTT Discovery, fresh and
retained values, start/stop transitions, defrost, persistent JSON,
and publication of eight Home Assistant MQTT sensors.

Remaining before production deployment: real broker, actual alpha13
sensor Discovery payload, true defrost semantics, on-device restart and
file permissions test. This is not a verified heat-pump installation.
