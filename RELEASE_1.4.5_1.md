# HaierPi 1.4.5_1 — Stable + diagnostics (RAM-only)

**Base:** official HaierPi `1.4.5_stable.tar.gz` published by [kamilostatek/hpi](https://github.com/kamilostatek/hpi/blob/main/1.4.5_stable.tar.gz) on 24 November 2026.

**Versioning:** `1.4.5_1` identifies this fork's **combined distribution**, not a rewritten upstream core. The enclosed `upstream/1.4.5_stable.tar.gz` is byte-identical to KamiloStatek's upstream release. Its `main.py` still reports upstream version `1.4.5`. Do not apply the old alpha13 patches again!

**Upstream SHA-256:** `ca803a3f8777efa75a40739d2efeb0362365ffa4291d3eb76d9a231c6cb53976`

## Verified upstream changes already present (not re-applied)

- Signed 12-bit PyHaier temperature decoding: 10 fixed conversion sites in six modules.
- Actual vs requested compressor frequency, including MQTT Discovery and downstream calculations.
- Signed Superheat/Subcooling formulas without absolute-value truncation.
- Legacy MQTT Discovery sensor cleanup (stable uses `for _legacy_sensor in (...)`).
- Independent R141/R241 freshness monitoring with 180-second staleness threshold.
- Existing stable UI, Modbus controls, schedules and application logic are **unchanged** in this fork.
- Stable brings additional upstream chart and control fixes beyond the alpha13 branch. No alpha files replace them.

## Our additions in 1.4.5_1

| Component | Service | Behaviour |
| --- | --- | --- |
| Compressor/defrost cycle monitor | `haierpi-cycles.service` | 8 MQTT Discovery sensors, counters entirely in process RAM |
| Refrigeration/hydraulic circuit diagnostics | `haierpi-circuit.service` | 6 derived MQTT Discovery sensors, read-only |
| Recovery on OverlayFS boot | `haierpi-startup/start.sh` | Restores service account, env and systemd units in the RAM overlay |
| Installation/verification | `install-diagnostics-light.sh` | Checks space, snapshots diagnostics, starts only the two services, verifies MQTT |

**Deliberately excluded:** SQLite historian, WAL, CSV database reports, `cycle_counters.json` live writes, legacy numeric-name service units, and any new compressor/heat-pump control commands.

Old MQTT `unique_id` identifiers containing the historical PR development prefixes are **retained** for continuity with 14 Home Assistant entities. These are internal compatibility IDs, not service names.

## Package layout

`1.4.5_1.tar.gz` unpacks into `HaierPi-1.4.5_1/`:

- `upstream/1.4.5_stable.tar.gz` — verified, unmodified stable core package.
- `upstream/1.4.5_stable.sha256` — reference checksum.
- `diagnostics/` — only the two read-only MQTT bridges and helpers.
- `deployment/haierpi-cycles.service`, `haierpi-circuit.service` — descriptive unit files.
- `deployment/haierpi-startup/start.sh` — boot script for the tested NanoPi layout.
- `install-diagnostics-light.sh` — diagnostics-only migration utility.
- `docs/` — operation and recovery instructions.
- `README.md` — this release note.

The archive is **not** a direct input to upstream `stable.sh`: its extra paths are deliberate. Only `upstream/1.4.5_stable.tar.gz` is eligible for the upstream installer, which must be handled as a separate **core upgrade**.

## Deployment precautions — actual NanoPi

The owner's live NanoPi already runs the two diagnostics services and has a reboot-tested postboot hook. **Do not reinstall or modify a working core simply to change the distribution number.** The unmodified stable archive can be verified with the upstream `stable.sh --check` procedure on a separate host.

For a new/eligible machine with **stable core already present**, unpack the distribution, review space/backup needs and run:

```sh
bash install-diagnostics-light.sh
```

The script does not install/overwrite the upstream core. It stages in RAM, installs the sidecar code once to `/opt`, and verifies MQTT. It does **not** persist `/etc` over an OverlayFS reboot. For compatible NanoPi, use the separately documented `docs/OVERLAYFS_AUTOSTART.md` one-time setup only after verifying UID/GID, source paths and recovery plan. Do not blindly append a duplicate boot hook.

### Safety and validation

- OverlayFS protects root; no periodic diagnostic history is written onto the SD card.
- Settings/passwords are derived from existing `/opt/config.ini` and held in RAM, never in `/boot`.
- Cycle totals start fresh at service restart; long-term history belongs in the Home Assistant recorder.
- On 25 November 2026, the diagnostics and boot startup were successfully restart-tested on the owner's NanoPi running the earlier patched alpha13 core.
- **The combination with the new upstream Stable core has been verified statically and in simulated MQTT tests, but has NOT been validated against live heat-pump hardware.** Release is therefore marked **prerelease**.
- There is no automatic or silent upgrade of the working NanoPi core.

See also: [Home Assistant dashboard](https://github.com/petec999/home-iot-telemetry/tree/main/home_assistant/dashboards) (maintained separately).
