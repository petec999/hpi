# Adaptive — current handover (2026-11-26)

Use the [branch README](../README.md) as the current installation reference. Last verified functional commit: `5cfd14153e394ef0296e3192b53f2a7169a2c51e`, [CI](https://github.com/petec999/hpi/actions/runs/45886053115).

## Current design

- Branch `feature/adaptive-learning`; Stable main, published release assets and Android remain separate.
- Keep existing GPIO/RS485, MQTT reconnect/PUBACK and HA watchdog patches. Do not reinstall core or overwrite existing settings.
- Auto learns bounded responses to confirmed reductions; uses Twi and Two, empirical Two STOP, stable-edge native threshold estimation and startup preparation. Never commands heat demand, setpoint or compressor speed.
- Saved Auto resumes after fresh eligible data. Experiment checkpoint survives restart but never resumes automatically; user must select Experiment to continue or Experiment – od nowa for a new session. Pending commands and in-flight cycles do not resume. Prior sessions without a checkpoint cannot be recovered.
- Passive reports and register watch operate independently of active ownership. Hysteresis observer diagnostics distinguish discarded attempts from repeated invalid polls; reason counts are RAM-only. Decoded values and frame timestamps share one captured set. See README for retention and storage paths.
- A04 experimental writer removed after unsuccessful field switching. A4A status/counters retained. Do not reintroduce raw write commands without validated protocol and owner/protection semantics.
- Separate tank heater status exists in alternate official first-generation Modbus documentation; that map is not the YR-E27 register map. No verified independent CWU heater command or native hysteresis setting. Software TANK hysteresis has not been implemented.
- HA panel command is maintained in [home-iot-telemetry](https://github.com/petec999/home-iot-telemetry/tree/main/home_assistant); no new dashboard.

## Verification

1. Confirm `systemctl is-active haier`, fresh R101/R141/R201/R241 and MQTT/HA watchdog.
2. Check authenticated `/v2/api/state` for current owner, readiness, blockers and readback. Do not infer actual Auto activation from an issued command.
3. Use `/v2/adaptive-report` for continuous-run metrics, thresholds, observation coverage and decisions. Compare like weather/target groups; no causal savings claim.
4. If a historical heater ownership marker remains, check the physical controller state; the retired writer does not issue OFF automatically.
5. Protect raw data and credentials. Hardware acceptance remains open.

## History

The older handover is preserved at [the last pre-cleanup revision](https://github.com/petec999/hpi/blob/3d9ae8eda2c7419c241a5933df74716fbebdc50c/docs/ADAPTIVE_HANDOVER.md). Its older Twi STOP, storage and boot descriptions are historical, not instructions for the current version.
