# HaierPi — stable core, diagnostics and experimental extensions

HaierPi fork for local heat-pump monitoring, Home Assistant/MQTT integration and opt-in CO modulation research.

## Start here

| Track | Status | Where to go |
| --- | --- | --- |
| Stable core 1.4.5 | Baseline; no experimental Adaptive or Android changes merged | This branch |
| 1.4.5_3 | Published prerelease with RAM diagnostics and HA MQTT watchdog | [Release and checksums](https://github.com/petec999/hpi/releases/tag/v1.4.5_3) |
| 1.4.5_4 | Reliability integration; packaged installer hardware validation pending; not published as a release | [Release notes](https://github.com/petec999/hpi/blob/release/1.4.5_4/RELEASE_1.4.5_4.md) |
| Adaptive preview | Latest verified revision 5cfd1415; native threshold learning, passive reporting, A4A heater status/counters; hardware validation open | [Installation and status](https://github.com/petec999/hpi/tree/feature/adaptive-learning) |
| Android 0.2.0 | Signed preview build; device/API acceptance tests pending | [Mobile app](https://github.com/petec999/hpi/tree/feature/android-app/android-app) · [APK build artifacts](https://github.com/petec999/hpi/actions/runs/45868217263) |

The experimental controller never replaces native compressor protection. Install only on compatible HaierPi systems with a backup and follow the instructions for the chosen track. Android uses the installed authenticated v2 API; it does not install firmware.

## Development status and remaining work

- [Open pull requests](https://github.com/petec999/hpi/pulls): only the deferred standalone SQLite historian (#4) remains open in this fork. Alpha13 fixes (#3) and earlier standalone cycle/circuit sidecars (#1/#2) were closed as superseded deployment paths, not merged. Their branches remain available for reference.
- [GitHub Actions](https://github.com/petec999/hpi/actions): automated tests and Android builds.
- [Adaptive handover and validation](https://github.com/petec999/hpi/blob/feature/adaptive-learning/docs/ADAPTIVE_HANDOVER.md).
- [Home Assistant dashboards](https://github.com/petec999/home-iot-telemetry/tree/main/home_assistant).

No experimental branch is automatically deployed or merged into Stable. The adaptive heater writer was retired after unsuccessful field switching; no independent tank heater command or configurable native DHW hysteresis has been verified. Published release assets are unchanged. Please report the installed version, sanitized logs and observed behavior when opening issues.

## Stable 1.4.5 — original change summary

Improvements and bug fixes

Pull Request #1 – Negative temperature decoding

Fixed incorrect decoding of negative temperatures in the PyHaier library.

Corrected 10 temperature conversion operations.

Pull Request #2 – Compressor diagnostics

Fixed reversed actual and target compressor frequency values (fact and fset).

Corrected Superheat and Subcooling calculations.

Removed absolute value conversion to preserve negative readings.

Pull Request #3 – MQTT Discovery

Improved Home Assistant MQTT Discovery handling.

Added cleanup of obsolete MQTT Discovery entities.

Pull Request #4 – Data freshness monitoring

Added freshness monitoring for R141 and R241 data frames.

Introduced a 180-second timeout for stale data.

Improved MQTT entity availability reporting in Home Assistant.

Separated MQTT connection status from heat pump data availability.

Additional fixes

Corrected actual and target compressor frequency mapping throughout HaierPi.

Fixed historical and live chart data mapping.

Fixed compressor frequency readings in the web interface and service panel.

Corrected compressor operation detection.

Corrected compressor frequency references in the Anti On-Off function.

Corrected compressor frequency references in DHW blocking and FLimit reset logic.

Preserved the existing Anti On-Off algorithm.

Ensured consistent compressor frequency mapping between HaierPi and Home Assistant.

Release and update improvements

Removed Alpha13 version identifiers.

Updated the application version to 1.4.5.

Updated the systemd service description and log identifier.

Added a dedicated Stable update script.

Added SHA256 package integrity verification.

Added automatic backup and rollback on update failure.

Preserved existing configuration, user accounts and historical chart data.

Thanks to all contributors for their pull requests, bug reports and support in improving HaierPi!
