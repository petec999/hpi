# PR #7 — derived circuit diagnostics (work in progress)

This feature is exclusively for **petec999/hpi**. No heating controls,
Modbus layout or existing MQTT entity IDs are changed.

## Six new calculations
1. Water-side ΔT (Two - Twi), °C
2. Saturation temperature lift (TSatPd_act - TSatPs_act), °C
3. Ambient-to-evaporation approach (Tao - TSatPs_act), °C
4. Discharge-to-condensation gap (Td - TSatPd_act), °C
5. Refrigerant pressure difference (Pd_act - Ps_act), MPa
6. Compressor requested minus actual frequency (fset - fact), Hz

These are **diagnostic differences**, not COP or manufacturer-defined fault
thresholds. Existing Superheat, Subcooling, Pd/Ps, EEV and compressor raw
sensors must NOT be duplicated. Raw EEV trajectory belongs in history/PR #8.

Data sources span R141 and R241. A value must only be calculated when both
blocks are fresh, in conjunction with the PR #4 freshness implementation.
Input bounds are sanity limits, not safe operating thresholds.
PR #2 fixes compressor requested/actual mapping, which is assumed here.

## Current state
- Pure, testable Python calculations are implemented.
- No modifications to the currently running heat pump.
- HA MQTT Discovery integration and actual payload layout validation are
  outstanding. Real hardware measurements are not yet validated.
- The six metrics should be exposed as read-only native MQTT Discovery
  sensors after confirming the running alpha13 snapshot fields.

## Local tests
```sh
python3 -m unittest discover -s tests -p test_circuit_telemetry_pr7.py -v
```
