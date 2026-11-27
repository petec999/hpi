# HaierPi Adaptive — experimental integrated preview

Opt-in anti-cycling supervision for existing HaierPi Stable 1.4.5 installations, with authenticated WWW v2, bounded online learning and read-only diagnostics.

**Current functional revision (2026-11-27):** [`f252db5b`](https://github.com/petec999/hpi/commit/f252db5bae2c6a47a7a1258a2cafdc2b6651c8df) — [Python 3.9/3.11 and Stable writer audit passed](https://github.com/petec999/hpi/actions/runs/45943635658). This is an experimental preview, not a production release. Physical acceptance of the latest version remains open.

## Install / update

On the HaierPi host, as root, only on a compatible existing installation:

```bash
REF=f252db5bae2c6a47a7a1258a2cafdc2b6651c8df
curl -fsSL "https://raw.githubusercontent.com/petec999/hpi/$REF/install-adaptive-preview.sh" -o /tmp/install-adaptive-preview.sh && bash /tmp/install-adaptive-preview.sh "$REF" --dry-run
```

Repeat with `--apply` after a successful dry-run and when a brief service restart is acceptable. The installer backs up modified files, checks fresh telemetry and attempts rollback on failure. Verify MQTT separately. No automatic remount or replacement of existing schedules and settings.

## WWW v2 (`/v2/`)

| Mode | Behaviour |
| --- | --- |
| Legacy | Original policy |
| Manual | User controls preset and FLimit |
| Shadow | Adaptive proposals only; legacy automation may still act |
| Auto | Experimental supervisor using the six preset/FLimit combinations |
| Experiment | Optional idle-only trials; three accepted cycles per configuration |

Auto does not command compressor frequency, demand or water setpoint. It preserves native and priority protections. Saved Auto waits for two distinct fresh sets of frames and eligible normal CO before resuming after restart. Manual/Legacy selection cancels resume. Failed commands or prolonged telemetry loss may disarm to Manual.

The experiment has no calendar deadline; completion restores the original combination at an eligible idle, then selects Manual. Its checkpoint survives restart, but it never automatically resumes: explicitly select Experiment to continue or Experiment – od nowa to begin a new session. The original combination is retained; cancellation/pause/restart does not itself restore it. Existing sessions started before checkpoint support cannot be reliably recovered. Progress is based on saved accepted cycles (bounded history); in-flight cycles are not saved.

## Diagnostics and data

- **Hysteresis rejection diagnostics:** current phase, blocker and rejected attempts by reason since service startup, without additional RS485 traffic. Strict cycles still require stable target and configuration. Frame timestamps and decoded values come from the same captured frame set.
- **Native threshold estimation:** empirical START near target −2 K (Twi/Two idle proxy); STOP near target +5 K (Two). Estimates require repeated stable observations; defaults remain when evidence is insufficient. Neither is a manufacturer-confirmed threshold. START/STOP ETA is a linear trend approximation shown only with recent stable samples in the matching context.
- **Last 24 hours:** read-only sampled compressor runtime, starts, CO, DHW, defrost, protection and missing-data coverage over 96 finished UTC quarters. No inference of power or energy. Storage is bounded, separate from the historical CO performance report.
- **Adaptive report:** `/v2/adaptive-report`, authenticated JSON and CSV, weather/target-matched Auto and Legacy groups, frequency-confirmed running time, continuous-operation KPIs, threshold samples and decision history.
- **Heater A4A:** read-only status, observed starts/runtime and last 128 transitions. The experimental A04 writer and MQTT controls were retired after unsuccessful field switching. No replacement writer is enabled. Existing core service/protection logic remains intact.
- **Register Watch:** passive raw frame comparisons, known signals and candidate changes; last 256 events. No additional RS485 traffic or writes. R101 bit 7 selects TANK, not tank heater output. Independent tank-heater command and native DHW hysteresis parameter remain unresolved.
- **HA:** [dashboard updater](https://github.com/petec999/home-iot-telemetry/tree/main/home_assistant) displays A4A and counters, not a switch.

### Storage

| File in /opt/haier | Bound / dirty save interval |
| --- | --- |
| .adaptive-experiment-v1.json | Original configuration and session start; atomic on selection/completion; no automatic resume |
| .adaptive-owner-v1 | Selected owner; atomic on selection |
| .adaptive-learning-two-v3.json | 1024 contexts, 512 KiB load cap; 30 min |
| .adaptive-hysteresis-v1.json | 128 cycles; 5 min |
| .adaptive-thresholds-v1.json | 24 samples per context, 1 MiB cap; 5 min |
| .adaptive-operation-v1.json | 100 quarter-hour buckets, 128 KiB cap; 30 min |
| .adaptive-report-v1.json | 90 UTC days / 2048 groups, 512 events, 2 MiB cap; 30 min |
| .adaptive-register-watch-v1.json | 256 events, 512 KiB cap; 30 min |
| .adaptive-heater-counter-v1.json | 128 transitions, 32 KiB cap; 30 min |

Data is sampled and bounded. Counters exclude gaps; they are not utility-meter readings. Unsaved observations may be lost on restart. A4A is a controller indication, not independently measured heater power. No raw household logs or historical HA data are uploaded or automatically imported.

## Further work

Hardware verification of Auto/learning and MQTT, evaluation of continuous run lengths versus Legacy, and read-only investigation of DHW. No savings claim or guarantee of continuous operation at minimum capacity.

- [Current handover](docs/ADAPTIVE_HANDOVER.md)
- [Earlier documentation and detailed evolution](https://github.com/petec999/hpi/blob/3d9ae8eda2c7419c241a5933df74716fbebdc50c/README.md)
- [Integrated preview guide (earlier design)](docs/INTEGRATED_ADAPTIVE_PREVIEW.md)
- [Stable and published releases](https://github.com/petec999/hpi#start-here)
- [Android preview](https://github.com/petec999/hpi/tree/feature/android-app/android-app)

Do not publish credentials or raw household telemetry.
