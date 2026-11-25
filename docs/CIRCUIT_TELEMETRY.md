# Read-only refrigeration and water-circuit diagnostics

The service is **`haierpi-circuit.service`**, implemented by
`diagnostics/mqtt_circuit_bridge.py`. It does not send heat-pump control
commands or modify the original controller.

## Exported measurements

1. Water temperature difference: Two − Twi, °C
2. Refrigerant saturation lift: TSatPd_act − TSatPs_act, °C
3. Ambient-to-evaporation approach: Tao − TSatPs_act, °C
4. Discharge-to-condensation gap: Td − TSatPd_act, °C
5. Refrigerant pressure difference: Pd_act − Ps_act, MPa
6. Requested minus actual compressor frequency: fset − fact, Hz

These are mathematical differences, not manufacturer-approved fault
thresholds, calculated COP, or thermal capacity. Input status must be
fresh for R141 and R241; the bridge also requires its connection state.
Pressure units are normalized according to MQTT Discovery.

MQTT output is under `<HPI_TOPIC>/diagnostics/circuit/`. The historical
Home Assistant `unique_id` prefix `HaierPi_PR7_` remains unchanged to
preserve the existing entities and dashboards. The device display name
and systemd unit are descriptive.

## Installation and runtime

Use `install-diagnostics-light.sh` for two-service diagnostics only.
Python 3.9+ and `paho-mqtt>=1.6,<2` are required. Credentials are derived
from the existing `/opt/config.ini`, never embedded in code or `/boot`.
The service stores no local historical database. Home Assistant handles
longer-term charts.

The actual device's OverlayFS postboot integration is described in
`docs/OVERLAYFS_AUTOSTART.md`. It was reboot-tested 25 November 2026.

## Tests

```sh
python3 -m unittest discover -s tests -p 'test_circuit_telemetry_pr7.py' -v
python3 -m unittest discover -s tests -p 'test_mqtt_circuit_bridge_pr7.py' -v
python3 -m unittest discover -s tests -p 'test_pr7_runtime_simulation.py' -v
```
