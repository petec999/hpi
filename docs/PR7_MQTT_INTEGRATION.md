# PR #7 — MQTT bridge for Advanced Circuit Telemetry

This branch now includes a **standalone MQTT bridge** in
`diagnostics/mqtt_circuit_bridge.py`. It reads existing HaierPi MQTT
Discovery definitions, subscribes to the actual source topics specified by
those definitions, computes six metrics and exposes them through MQTT Discovery.

## Dependencies / prerequisites

- Python 3.10+ with `paho-mqtt`.
- HaierPi MQTT enabled and MQTT Discovery enabled, with all ten source
  sensor configurations retained on the broker.
- Separate R141 and R241 freshness topics and HaierPi bridge availability
  from upstream PR #4 or an equivalent local implementation.
- Correct compressor actual/set mapping from PR #2 or equivalent.
- Working MQTT broker accessible from the host running this sidecar.

This intentionally does **not** change `alpha13.sh` or application
`main.py`. Run sidecar in a separate process; it cannot change heat pump
control registers. Do not launch it without first validating the source
unique IDs and MQTT Discovery configuration against your actual broker.

## Start example

```sh
python3 -m pip install paho-mqtt
export HPI_MQTT_HOST=127.0.0.1
export HPI_MQTT_PORT=1883
export HPI_TOPIC=climate/haier
export HPI_DISCOVERY_PREFIX=homeassistant
export HPI_MQTT_USERNAME=your_mqtt_username
export HPI_MQTT_PASSWORD=your_mqtt_password
python3 -m diagnostics.mqtt_circuit_bridge
```

Configuration: `HPI_SAMPLE_TTL` defaults to 150 seconds; maximum 180.

## Automatically discovered Home Assistant sensors

- CO water delta T (°C)
- Refrigerant saturation lift (°C)
- Ambient evaporation approach (°C)
- Discharge condensing gap (°C)
- Refrigerant pressure delta (MPa)
- Compressor frequency deviation (Hz)

Discovery unique IDs are prefixed `HaierPi_PR7_`. Nothing overwrites
existing HaierPi pressure, EEV, Superheat, Subcooling or compressor entities.

Availability is `offline` until the sidecar has discovered all ten source
sensors, received **new non-retained samples** for all of them, and all
three availability topics are online. It turns offline again when telemetry
is stale or communication is lost. Nonretained messages must arrive
regularly: 150 s is a conservative initial limit, not a protocol guarantee.

## Limitations

- This is a deployable **sidecar design**, not an installer: no systemd
  service or automated deployment has been configured.
- Its MQTT interpretation supports numeric values, simple
  `value_json[index]`, and `value_json.field` templates. It intentionally
  rejects more elaborate arbitrary Jinja templates.
- Source unique IDs and default topic prefixes are derived from the
  alpha13 PR #2/#4 metadata, not yet proven against a live MQTT capture.
- If prerequisite R141/R241 status topics are missing, output stays offline.
- It does not calculate COP or thermal capacity.
- End-to-end tests against live HaierPi + broker + Home Assistant are still
  required before calling the integration verified on your installation.

## Regression tests

```sh
python3 -m unittest discover -s tests -p 'test_circuit_telemetry_pr7.py' -v
python3 -m unittest discover -s tests -p 'test_mqtt_circuit_bridge_pr7.py' -v
```
