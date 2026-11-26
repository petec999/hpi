# Adaptive modulation — experimental design

This branch is not a live controller. The policy module is pure Python, returns proposals only, and has no GPIO, serial, MQTT, or file writes. No live-control installation on HaierPi yet.

## Ownership

- Legacy: original Stable logic unchanged.
- Manual: operator owns the preset and FLimit relay; automatic CO preset/relay writers must yield. Native heat demand, frost protection, defrost, and existing safety functions remain independent.
- Shadow: leave existing output ownership unchanged; compute and log proposals only, alongside the current Legacy or Manual behavior.
- Auto: exclusive adaptive owner of CO preset and FLimit. Manual command should atomically move to Manual before changing outputs, or be rejected explicitly. Returning to Auto begins from confirmed actual state, not a stored requested state.
- DHW/defrost/service/protection have priority. Existing manual/off frequency-limit selections must be reconciled explicitly, not silently overridden.
- Outdoor zones initially remain hard bounds if explicitly selected; optional preferences must not impose permanent low capacity when sustained demand is high. No change to room target or heating curve.

## Policy

All six preset/relay combinations are recognized. They are not a globally ranked list of power or compressor speed. Candidate moves change just one output: on shortage release FLimit first, then increase preset; on surplus enable FLimit first, then lower preset while retaining the limit. This is a testable directional policy, not a guarantee of physical capacity ordering.

Use the supply error (target minus Two) as the primary tracking signal and return deficit/trend as supporting context. Normal water-side temperature difference is not a supply shortage. Calculate robust median trends over 150 seconds and a bounded three-minute forecast of surplus. Integrate sustained positive supply error with decay in K*min, not energy units. Confirm large shortages for 60 seconds and normal shortages for 120 seconds. Reduce on persistent or predicted surplus before shutoff, including an early path after 180 seconds of settling; normal downward confirmation 90 seconds. Stable high-frequency operation can trigger an optional exploratory reduction after 15 minutes. These are provisional tuning constants, not manufacturer shutoff limits.

Only a matching actually observed reduction starts a trial; a later confirmed shortage proposes restoring the previous combination and suppresses the same failed reduction for 30 minutes. A proposal is not a confirmed command; shadow cannot establish why a user or legacy controller changed the mode. Reset observations on target changes, invalid telemetry, defrost, service override or compressor stop. No forced starts, stops, setpoint changes or bypass of factory protections.

## Required before live integration

1. Verify actual frame freshness (R141/R241, confirmed target, actual preset, GPIO readback), not merely MQTT heartbeat or presence of a snapshot.
2. Audit all preset/FLimit writers (curve, zones, DHWWL restoration, flimitreset, UI/MQTT and service paths); ensure exclusive ownership and safe handoff. Preserve manual priority and factory protections.
3. Implement shadow adapter, report observed decisions and suppression reasons. Record frequency and cycles; no counterfactual energy-saving claim from replay. Observer exists; cycle aggregation and control adapter remain pending.
4. Validate capacity envelopes against actual frequency/current/thermal behavior, confirm write/readback and cooldown. Handle unusual preset+relay combinations without guessing. Add independent fallback and explicit opt-in for live mode.
5. Test real-world traces (mild weather, cold weather, defrost, changed target, sensor loss, compressor restart, manual overrides), then supervised limited auto operation.

Current policy uses frequency as validity/activity input and a conservative stable-operation probe condition, not calibrated saturation feedback. Proposed parameters are starting points only. No UI or HA entities yet.

## Foreground shadow observer

The optional adaptive.shadow module reads new local journal status_snapshot messages and subscribes to the three existing availability topics. It requires a live non-retained connected heartbeat (the v2 PUBACK refresh), both R141/R241 freshness flags, a recent snapshot, and a valid operating state. It resets its history on disconnect, process identity change, data interruption or invalid sample. It does not publish MQTT messages or change any device files. Existing controls continue to own outputs regardless of the observer. Use the existing diagnostics Python environment with Paho 1.x.

Run from an isolated checkout, as a user with journal and config read permission:

    /opt/haierpi-diagnostics/.venv/bin/python -m adaptive.shadow

Stop with Ctrl+C. JSON output includes actual and proposed envelope, delta, trend, reason and freshness flags. A proposal is not a prediction of exact frequency or savings; no actuation occurs. The observer can compare against the current Legacy behavior without altering ownership.

Limitations: Stable's availability flags have a 180-second source freshness threshold, not precise frame timestamps; journal snapshot age is independently checked. The reported heating curve is not independently confirmed pump setpoint readback. These limitations are acceptable for observation only, not for live control. Direct frame ages, readback, verified ownership and hardware validation remain prerequisites for Auto.

## Real trace regression

The user-provided Turbo+FLimit trace: supply target 32 C, Two 32.2 to 33.1 C, Twi 29.1 to 29.9 C, actual/requested frequency 45 Hz. The manual change to Eco+FLimit produced 40 Hz in the observed samples. This does not establish a universal frequency ceiling or prove energy savings. Regression replay checks the policy proposes Eco+FLimit during the observed surplus, rather than treating the normal return deficit as a power shortage. Additional tests cover persistent small deficits, urgent release, a failed reduction followed by restoration, deadband noise, manual/legacy modes and stale telemetry.

## Manufacturer reference (model family, not confirmed installed model)

Haier Super Aqua service manual 2023, pp. 1–2, 27–31, 62–63, 120–121 and 132:
https://www.haier-ac.pl/wp-content/uploads/materialy/instrukcje/pompy_ciepla/2023_haier_instrukcja_serwisowa_pompa_ciepla_super_aqua_co_cwu.pdf

The manual describes the ATW-A01 CN23 dry contact as reducing the maximum operating frequency by 50%; this is not a promise of half the heat output or lower minimum frequency. It lists separate requested and actual compressor frequency service values. The heating capacity tables depend on outdoor and water temperature, with minimum/nominal/maximum output; models use different compressors. It also specifies minimum active water volume to reduce cycling. Do not extrapolate a fixed Hz-to-kW conversion or exact minimum frequency from these tables. No model-specific numbers are embedded in the control policy until the exact installed model and applicable manual are confirmed. The regulator also suppresses a downward move if both requested and actual frequency are already falling rapidly. Early surplus forecast threshold 0.9 K is experimental, not a factory trip threshold.

## Historical replay (initial exploratory evaluation)

Offline evaluation on 30-second aligned HA history, 17–26 November 2026. No household-level history committed. The aligned series had 25,920 rows; only the final part had explicit R141/R241 freshness flags. On a local reproduction of policy at 71ec16b, a preselected set of 65 candidate CO stops (stable demand and mode, no defrost) included 55 at Quiet+FLimit; all 10 other stops had a reduction proposal within the preceding 15 minutes (lead 3.5–15 minutes, truncated at 15 minutes). Only two of those stops had explicit freshness flags and both had a prior proposal. This is exploratory, not a controlled outcome or a factory shutoff threshold. Historical service flags and confirmed pump target are missing; curve and displayed setpoint differ in the history. Proposals are per sample, not executed transitions. The next step is testing actual readback and ownership, not promising to eliminate 65 stops. The new offline CSV replay utility is separate from this local evaluation and must be validated before using it for production metrics. No user telemetry uploaded.

Native requested frequency zero now pauses the policy even when actual speed has not yet reached zero; diagnostic cycling risk is visible during settling. These changes require regression checks.

## Superseding Twi-v2 policy
The running controller now uses Twi as the primary signal, forecast Twi surplus and distance to assumed STOP target+5 K. Two corroborates shortages; Two surplus alone does not trigger a reduction. The original trace with Twi 29.1–29.9 and Two 32.2–33.1 now intentionally holds. All historical replay counts above refer to the prior policy, not validated results for Twi-v2. Margin and thresholds are experimental supervisory settings, not factory parameters. New learning schema isolated from old model.
