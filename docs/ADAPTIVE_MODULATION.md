# Adaptive modulation — experimental design

This branch is not a live controller. The policy module is pure Python, returns proposals only, and has no GPIO, serial, MQTT, or file writes. No live-control installation on HaierPi yet.

## Ownership

- Legacy: original Stable logic unchanged.
- Manual: operator owns the preset and FLimit relay; automatic CO preset/relay writers must yield. Native heat demand, frost protection, defrost, and existing safety functions remain independent.
- Shadow: same output ownership as Manual; compute candidate policy decisions, log only. For comparison with existing automation an optional read-only Legacy observer can be added separately.
- Auto: exclusive adaptive owner of CO preset and FLimit. Manual command should atomically move to Manual before changing outputs, or be rejected explicitly. Returning to Auto begins from confirmed actual state, not a stored requested state.
- DHW/defrost/service/protection have priority. Existing manual/off frequency-limit selections must be reconciled explicitly, not silently overridden.
- Outdoor zones initially remain hard bounds if explicitly selected; optional preferences must not impose permanent low capacity when sustained demand is high. No change to room target or heating curve.

## Policy

Four candidate envelopes: Quiet+FLimit, Quiet, Eco, Turbo. The actual ordering and effect on minimum versus maximum frequency are hypotheses to validate against telemetry and the specific Haier unit. Factory inverter remains responsible for actual frequency. Median return-temperature deficit and trend, directional hysteresis, dwell times, rapid one-level release for sustained severe deficit. No forced compressor starts/stops. State must be based on actual confirmation. Timing uses a monotonic clock in a future adapter.

## Required before live integration

1. Verify actual frame freshness (R141/R241, confirmed target, actual preset, GPIO readback), not merely MQTT heartbeat or presence of a snapshot.
2. Audit all preset/FLimit writers (curve, zones, DHWWL restoration, flimitreset, UI/MQTT and service paths); ensure exclusive ownership and safe handoff. Preserve manual priority and factory protections.
3. Implement shadow adapter, report observed decisions and suppression reasons. Record frequency and cycles; no counterfactual energy-saving claim from replay.
4. Validate capacity envelopes against actual frequency/current/thermal behavior, confirm write/readback and cooldown. Handle unusual preset+relay combinations without guessing. Add independent fallback and explicit opt-in for live mode.
5. Test real-world traces (mild weather, cold weather, defrost, changed target, sensor loss, compressor restart, manual overrides), then supervised limited auto operation.

Current policy uses frequency as validity/activity input, not calibrated saturation feedback. Proposed parameters are starting points only. No UI or HA entities yet.

## Foreground shadow observer

The optional adaptive.shadow module reads new local journal status_snapshot messages and subscribes to the three existing availability topics. It requires a live non-retained connected heartbeat (the v2 PUBACK refresh), both R141/R241 freshness flags, a recent snapshot, and a valid operating state. It resets its history on disconnect, process identity change, data interruption or invalid sample. It does not publish MQTT messages or change any device files. Existing controls continue to own outputs regardless of the observer. Use the existing diagnostics Python environment with Paho 1.x.

Run from an isolated checkout, as a user with journal and config read permission:

    /opt/haierpi-diagnostics/.venv/bin/python -m adaptive.shadow

Stop with Ctrl+C. JSON output includes actual and proposed envelope, delta, trend, reason and freshness flags. A proposal is not a prediction of exact frequency or savings; no actuation occurs. The observer can compare against the current Legacy behavior without altering ownership.

Limitations: Stable's availability flags have a 180-second source freshness threshold, not precise frame timestamps; journal snapshot age is independently checked. The reported heating curve is not independently confirmed pump setpoint readback. These limitations are acceptable for observation only, not for live control. Direct frame ages, readback, verified ownership and hardware validation remain prerequisites for Auto.
