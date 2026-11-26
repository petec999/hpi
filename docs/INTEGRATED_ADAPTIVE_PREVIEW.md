# Integrated adaptive preview for 1.4.5 Stable

This is an opt-in **experimental preview**, not an upstream release or a validated hardware controller. It integrates the 1.4.5_4 core (GPIO, RS485 initial receive state, MQTT reconnect/PUBACK and HA watchdog), the previously device-tested Stage 2 WWW v2, and the adaptive policy. It preserves the existing configuration, original WWW and diagnostic sidecars. No reset, remount or clean installation.

## Installation and rollback

Download the terminal installer from a pinned commit and pass that same 40-character commit to it. Without --apply it only stages and compiles the changes. With --apply it requires root on HaierPi, validates every source anchor before writes, saves original main.py and HPi/GPIO.py if changed, replaces them atomically, and restarts haier once. It checks two independently renewed sets of four complete RS485 frames in the new service invocation and a valid snapshot; failure triggers automatic restoration and restart. A systemd invocation ID and journal are required. It does not verify end-to-end Home Assistant delivery; check existing watchdog separately. A power loss during file replacement is not an atomic two-file transaction; retain the printed backup.

The wrapper downloads nine source files into a temporary directory from the same immutable Git commit. It does not download or overwrite the original Stable archive, install packages or change the service definition. Unknown WWW v2 variants are rejected. The initial preview marker prevents accidental double installation; supported preview upgrades explicitly handle migration. Use the pinned installer in the branch README.

Open the existing HaierPi address plus /v2/ and log in as usual. New card: AntiON-OFF v2.

## Control selection

- Legacy (default after **every service restart**): the original preset/FLimit policy remains in charge.
- Shadow: the original policy remains in charge; adaptive proposals shown without writes.
- Manual: suppress normal automatic CO preset/relay writers; manually select Quiet/Eco/Turbo and FLimit in WWW. Explicit priority modes and protections remain authoritative.
- Auto: opt-in; uses actual four-frame snapshot and the adaptive policy. It is independent of stored legacy FLimit and preset policies, and requires a normal outdoor zone, valid sensors, no conflicting safety/DHW operation and actual CO target within 1 K of computed curve. It never changes heat demand, water setpoint or starts/stops the compressor. Explicit manual profile or relay command takes over as Manual when Auto is enabled (provided no priority operation or outstanding command). The existing MQTT and original WWW manual command paths are included.
- Frost/warm forced zones, DHW override/restoration, defrost and antifreeze remain priorities. Disable optional forced preset zones in existing settings only if you want adaptive decisions throughout their temperature range; do not disable factory protections. Auto pauses outside normal zone.
- Stale data pauses adaptive writes; prolonged data loss, failed write/readback or exceptions disarm into Manual hold. Pending write confirmation blocks other adaptive writes. Only a confirmed subsequent R201 preset frame and physical sysfs GPIO readback can clear pending state.

- Experiment: opt-in, six preset/FLimit combinations, three accepted cycles each, no calendar limit. Commands only at confirmed idle with demand, normal CO and fresh readback; priority operations or failures may disarm. On completion restore the initial combination at an eligible idle, then switch to Manual. Restart resets the session; manual cancellation does not restore prior outputs.

State selection is session/process-wide, not saved into config. Auto never starts by itself after reboot. Core serial writes share a lock to prevent simultaneous submissions to the existing single-slot mailbox. Existing protocol parsing is unchanged: complete register counts are not a new CRC implementation. A pending timed-out legacy write may still complete; no automatic adaptive retry. GPIO readback verifies the output pin, not the physical relay contacts. Curve and actual CH target are kept distinct. The new panel uses the existing authenticated CSRF-protected control route. All runtime controls are local; no new MQTT discovery entities added in this preview.

## Validation

Unit tests on Python 3.9/3.11, mocked ownership/readback/telemetry tests, pinned Stable archive checksum, actual PyHaier decoder export checks, full source patch and idempotence. MQTT and GPIO core tests passed separately in release/1.4.5_4. Integrated preview has been installed and initial telemetry observed on a real pump. Full Experiment completion/restoration and validated Auto regulation remain open; keep Legacy or Shadow when not explicitly testing. Do not enable Auto unattended on the first hardware test. Current Auto STOP margin is provisional (Twi +5 K); the passive observer does not update it. No promise of eliminating all cycles, especially when heat demand is below the pump's physical minimum. Existing historical replay is observational, not a counterfactual proof.

## Supply STOP model and restart behavior (26 November 2026)

Verified functional revision: `dde94a1fa23f2b772e55787597b09966389b63da` ([CI](https://github.com/petec999/hpi/actions/runs/45873317440)). STOP risk uses current Two and its short-horizon forecast against actual water target +5 K, with a provisional 1 K warning margin; Twi remains a return-demand and surplus signal. This is an empirical model, not a factory threshold. No changes to native demand, temperature target or compressor protection. Learning starts in a new file `.adaptive-learning-two-v3.json`, retaining old files; the passive observer continues using the same store. Explicit Auto selection is persisted atomically in `.adaptive-owner-v1`. After reboot, Auto waits in Manual hold for two independent fresh frame sets, valid normal CO, demand and no priority override. Explicit Manual/Legacy/Shadow/Experiment selection cancels Auto resume; failures persist Manual where storage is writable. If storage cannot be updated, a visible error warns that a saved choice may survive a restart. No experiment or pending command is resumed. Hardware verification remains open.
