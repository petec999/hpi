# HaierPi Adaptive — experimental integrated preview

**Status (2026-11-26):** CI passed on Python 3.9/3.11 and Stable writer audit. Real pump validation remains open; this is not a production release.

[Latest verified functional commit](https://github.com/petec999/hpi/commit/76eabc3f714f92c8606189e22ad5e8520c2ef27a) · [CI results](https://github.com/petec999/hpi/actions/runs/45875592144) · [Operating and rollback guide](docs/INTEGRATED_ADAPTIVE_PREVIEW.md) · [Handover](docs/ADAPTIVE_HANDOVER.md)

## Update a compatible existing HaierPi

Use the pinned functional revision, not an unreviewed branch HEAD. Run on the HaierPi host as root.

```bash
REF=76eabc3f714f92c8606189e22ad5e8520c2ef27a
curl -fsSL "https://raw.githubusercontent.com/petec999/hpi/$REF/install-adaptive-preview.sh" -o /tmp/install-adaptive-preview.sh && bash /tmp/install-adaptive-preview.sh "$REF" --dry-run
```

Repeat with `--apply` only after a successful dry-run and when a brief service restart is acceptable. The installer backs up modified files, verifies fresh four-frame telemetry and attempts rollback on failure. Check the HA watchdog separately. A restart restores saved Auto only after valid telemetry and normal heating demand; without saved Auto, starts in Legacy or Manual hold. Experiment sessions reset; saved measurements survive. Do not interrupt an active experiment just for a documentation update.

## Operating modes in /v2/

| Mode | Behavior |
| --- | --- |
| Legacy | Original automation; default without a saved selection |
| Manual | Manual preset/FLimit; normal legacy modulation blocked |
| Shadow / Obserwacja | Adaptive proposals only; legacy automation may still act |
| Auto | Experimental adaptive modulation; supply STOP model and saved Auto resume |
| Experiment | Opt-in preset/FLimit trials during confirmed idle only |

Experiment: Eco OFF → Quiet OFF → Quiet ON → Eco ON → Turbo ON → Turbo OFF; three newly accepted cycles per configuration, no calendar deadline. Completion restores the starting combination at an eligible idle, then selects Manual. Priority writes and command/telemetry failure can disarm to Manual. Manual cancellation and service restart do not guarantee restoration.

## Evidence and outstanding validation

- Observer measures Twi, Two and their average relative to the actual setpoint at Fset transitions. Stores pre/post frequency, outdoor temperature, water delta, run duration and sampled time above target bands. No automatic application of measured hysteresis.
- Auto uses a provisional Two +5 K STOP model based on observed historical behavior, **not** a factory-confirmed threshold; passive measurements continue.
- Experiment progress counts by configuration; threshold statistics keep exact target, owner, preset and relay separate. Changes in conditions may invalidate cycles or slow collection.
- Persisted cycle data: `/opt/haier/.adaptive-hysteresis-v1.json`; 128 recent cycles, atomic saves at most every five minutes. Auto response learning is separate: `/opt/haier/.adaptive-learning-two-v3.json`. Unsaved data can be lost.
- Remaining: representative per-context samples and real-world Auto modulation, restart and readback verification. The experiment is optional. No verified savings or guarantee of eliminating cycling.

Android companion: [native app 0.2.0](https://github.com/petec999/hpi/tree/feature/android-app/android-app).

---

## Historical 1.4.5_3 release instructions

The following section is for the earlier published diagnostic prerelease, **not** the current Adaptive installer.

Current distribution: **[1.4.5_3 (prerelease)](https://github.com/petec999/hpi/releases/tag/v1.4.5_3)**. This branch contains the complete installation sources, not a replacement for upstream Stable 1.4.5.

## Quick update on an existing compatible HaierPi

Run on NanoPi as root. For existing diagnostics, install only the watchdog:

```bash
cd /tmp
BASE=https://github.com/petec999/hpi/releases/download/v1.4.5_3
curl -fsSLO "$BASE/1.4.5_3.tar.gz" &&
curl -fsSLO "$BASE/1.4.5_3.sha256" &&
sha256sum -c 1.4.5_3.sha256 &&
tar -xzf 1.4.5_3.tar.gz &&
cd HaierPi-1.4.5_3 &&
bash install-1453.sh --dry-run &&
bash install-1453.sh --watchdog-only
```

For a compatible core without the two RAM diagnostic services, use `bash install-1453.sh` instead. This is not a full core upgrade. The installer creates backups and preserves the initial mount flags, including RW if already writable.

Verify:
```bash
grep -n 'HOME-IOT MQTT WATCHDOG' /opt/haier/main.py
journalctl -u haier -b --no-pager | grep -i watchdog
systemctl is-active haier
```

## Validation, 25 November 2026

```text
# HOME-IOT MQTT WATCHDOG v2
14:00:00 MQTT watchdog OK: HA confirmed heartbeat (failures=0 recoveries=0)
active
```

[CI build and simulated failure/recovery tests](https://github.com/petec999/hpi/actions/runs/45618747904) passed. Hardware installation and normal HA round-trip are confirmed. Actual outage/reconnect, persistent notification and reboot tests remain open; automatic RO remount was not tested because /opt was already RW. Do not interrupt a working heating system solely to test these paths.

## Documentation

- [Release notes and architecture](RELEASE_1.4.5_3.md)
- [MQTT watchdog, prerequisites and rollback](docs/MQTT_END_TO_END_WATCHDOG.md)
- [OverlayFS startup](docs/OVERLAYFS_AUTOSTART.md)
- [Home Assistant dashboard setup](https://github.com/petec999/home-iot-telemetry/blob/main/home_assistant/README.md)

Published archives and tags are immutable; later README updates do not modify the released archive or its checksum.

## Supply STOP model and restart behavior (26 November 2026)

Verified functional revision: `76eabc3f714f92c8606189e22ad5e8520c2ef27a` ([CI](https://github.com/petec999/hpi/actions/runs/45875592144)). STOP risk uses current Two and its short-horizon forecast against actual water target +5 K, with a provisional 1 K warning margin; Twi remains a return-demand and surplus signal. This is an empirical model, not a factory threshold. No changes to native demand, temperature target or compressor protection. Learning starts in a new file `.adaptive-learning-two-v3.json`, retaining old files; the passive observer continues using the same store. Explicit Auto selection is persisted atomically in `.adaptive-owner-v1`. After reboot, Auto waits in Manual hold for two independent fresh frame sets, valid normal CO, demand and no priority override. Explicit Manual/Legacy/Shadow/Experiment selection cancels Auto resume; failures persist Manual where storage is writable. If storage cannot be updated, a visible error warns that a saved choice may survive a restart. No experiment or pending command is resumed. Hardware verification remains open.

### Learning storage capacity

Auto response learning retains up to 1024 contexts in the existing `.adaptive-learning-two-v3.json` file (unchanged schema, up to 512 KiB on load). Dirty state is saved atomically at most once per 30 minutes per process; the first dirty save can be immediate if no file was loaded. The least recently updated context is evicted only when adding a new context at capacity. Existing valid learning records survive the update. A sudden outage may lose unsaved observations; an incomplete trial is not restored. The separate passive hysteresis observer retains its existing 128-cycle limit and five-minute save cadence.


## Adaptive report

In WWW v2 select **Raport Adaptive**, or open `/v2/adaptive-report`. It is an authenticated read-only page. Refresh on demand; JSON and CSV endpoints export observed daily groups, learned contexts and recent events. No SQLite and no external connection. Data is saved to `/opt/haier/.adaptive-report-v1.json` independently of the learning and hysteresis stores; dirty saves at most once per 30 minutes. Retains up to 90 UTC days/2048 daily groups, 512 recent events and cumulative scores since report initialization. A restart loses in-flight cycles and unsaved data, not saved aggregates. Existing learned contexts are shown immediately; new score counts start with the report.

Performance sampling uses independent fresh four-frame sets in eligible normal CO, with demand and no protection/priority. It counts observed Fset starts, complete Fset runs confirmed by Fact, actual running time by preset/FLimit and observed coverage; preset or FLimit changes do not break a performance cycle. Gaps, priority or owner/target-band changes interrupt it. Counts are not whole-day meter totals. Weather/target comparison groups by 5 K outdoor and 3 K target bands, and displays only groups observed under both Legacy and Auto; sample counts and observation time remain visible. Historical Home Assistant exports are **not automatically imported** and owner attribution for old logs is not assumed. No causal savings/COP claim. Do not switch a working installation to Legacy solely to fill the report.

Reporting is observational; controller behavior is unchanged. Hardware/browser verification still open. Functional commit `76eabc3f714f92c8606189e22ad5e8520c2ef27a`: [passing CI](https://github.com/petec999/hpi/actions/runs/45875592144).

## Learned native START / STOP model

Independent stable-edge observations, not the strict whole-cycle hysteresis observer, are stored in `/opt/haier/.adaptive-thresholds-v1.json` (up to 24 samples per edge, preset/FLimit and 3 K water-target band, five-minute dirty saves). Separate START and STOP estimates can be learned even when Auto changes configuration during a cycle. Samples require eligible fresh normal CO, stable owner/configuration/setpoint and phase for at least 120 seconds before the Fset edge, narrow water-temperature brackets, and Fact confirmation with 60 seconds of uninterrupted post-edge observation (maximum 180 seconds). Eight or more samples, MAD <= 0.35 K, at least 80% within 0.6 K of median and an allowed range are required. Default START -2 K, STOP +5 K; learned bounds START -3.5 to -1 K, STOP +3.5 to +5.5 K. START is a proxy using mean Twi/Two only when both agree during idle; the actual native START sensor is not identified. STOP uses Two. The learned STOP drives the existing reduction/shortfall veto and response scoring with the 1 K warning margin; START provides an idle cooling ETA and readiness indication. Auto still prepares Quiet+FLimit during confirmed idle. It may preserve a confirmed STOP sample for one additional tick only when both water temperatures are at least 2 K above predicted START and no imminent START forecast; it never commands the compressor, demand or setpoint. Estimates revert to defaults when evidence is insufficient or inconsistent. Existing learning/report files are unchanged. WWW v2 and Raport Adaptive show thresholds, sources, sample counts and dispersion. No automatic import from HA history; new observations are collected locally. Real pump validation remains open.
