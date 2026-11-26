# Web UI v2 — experimental preview on HaierPi 1.4.5_3

The original interface and control logic remain available; no MQTT callback is modified. The new authenticated routes are GET `/v2/`, GET `/v2/api/state` and POST `/v2/api/control`. The installer requires the existing watchdog v2 marker and a recognized authenticated Flask route. It refuses unexpected sources or read-only mounts, backs up main.py and restarts haier once; the shell wrapper restores the backup on startup failure. It does not alter mount flags, upstream archives, HA, MQTT topics, Modbus or control functions.

Data is limited to an explicit allowlist of cached source measurements, not the full status dictionary. R141/R241 freshness gates each measurement; derived differences require the relevant frames. The panel distinguishes MQTT broker connectivity from HA readback. No extra RS485 or MQTT requests, no database, no CDN; chart history is limited to ten minutes in the browser. Missing values remain unavailable. The hydraulic schematic is generic. This preview exposes pressure data; sidecar counters remain in Home Assistant. Historical charts and full settings remain in the original UI.

## Installation on existing 1.4.5_3

Download the two source files at a reviewed commit, put the Python file in `tools/` next to the shell wrapper. Run `bash install-web-ui-v2.sh --dry-run` first, then `bash install-web-ui-v2.sh`. Open the normal HaierPi address, log in using the original UI, and append `/v2/`. Existing WWW remains available at `/`.

Only deploy on a trusted local network or VPN. The new endpoints reuse the existing login system; known upstream authentication/session issues are not fixed by this preview. Never publish the controller directly to the Internet.

Rollback: use the printed wrapper backup path, restore it to /opt/haier/main.py preserving permissions, then restart haier. Do not restore an old backup over unrelated subsequent changes. Future upstream upgrades may remove the patch.

CI checks synthetic Flask authorization, GET-only telemetry API, filtering, missing/stale data, field mapping, and applies the patch to the SHA-pinned Stable archive with the existing watchdog installer. It does not run the actual controller or validate real sensor data. Live validation is required. Published v1.4.5_3 assets and main remain unchanged.

## Mobile control preview

The bottom mobile navigation remains visible while scrolling. The new control cards expose PCH and PDHW on/off, CH and DHW target temperatures in 0.5°C steps and Eco/Quiet/Turbo profile. The intentionally conservative preview limits are 20–45°C for the CH setting and 35–55°C for DHW; original UI retains its full existing ranges. CH uses the existing heat target/curve handling (not a direct forced outlet temperature); changing DHW target does not enable DHW. Advanced configuration and historical charts open the original UI; manual curve and weekly schedule now have native editors as described below.

Commands call the existing statechange, new_tempchange and new_presetchange handlers, preserve direct-mode curvecalc behavior and do not call Modbus directly. The POST endpoint requires existing login, session CSRF token, matching Origin, explicit command allowlist, expected previous value, both fresh frames and a nonblocking single-command lock. No automatic resend. The browser distinguishes pending from observed matching cached state, which is **not** independent hardware confirmation. Existing R101/R201 data lack per-block freshness; actual control and safety behavior must be verified on-device. Existing upstream authentication issues remain; LAN/VPN only.

The installer now recognizes and upgrades the exact original v2 preview block from commit 7961a18, or installs on a clean compatible 1.4.5_3. Unknown modifications fail closed. Always download both updated installer files from the same commit. A dry run validates the migration; actual deployment restarts haier once. No device changes have been performed by CI.

## Expanded mobile preview, regression-safe revision

Following loss of pump telemetry during the first expanded preview, restored the known-good basic controls version. The exact cause has not been established; the MQTT callback tap is removed as a precaution. The patched source outside the v2 block must be byte-for-byte identical to the known-good core.

- Pressure data Pd/Ps, with original bar units and R241 freshness gate.
- NanoPi uptime, 1-minute load, available/total RAM, /opt space and optional thermal-zone temperature.
- Independent authenticated optional diagnostics endpoint: failure does not invalidate the core frame state.
- True tabs and local last-tab preference.
- Manual curve editor: fourteen original outdoor temperature intervals; 25–55°C (20–55°C Expert), 0.5°C increments. Original settings writer and reload, non-atomic config write; no new curve algorithm.
- A03 compensation: original new_tempcompchange, -15…15°C step 0.5°C.
- Weekly CO/CWU scheduler editor: original validation and atomic schedule writer. No activation/deactivation changes; missing/invalid files are not overwritten.
- Cycle counters remain in Home Assistant until a separate, non-invasive interface is validated. No callback hook or extra service.

The installer requires valid water, compressor and pressure telemetry in the current systemd invocation's recent journal before making changes. After restart, it checks fresh-process status_snapshot entries for valid measurements for up to 120 seconds. If verification fails, it restores the backup and restarts the previous version, checking telemetry again. This requires systemd invocation IDs and INFO status_snapshot logging. This is a startup smoke test, not a continuous freshness proof.

Only the two known-good earlier preview blocks and compatible unmodified core are accepted. The failed expanded preview must be rolled back first. Real hardware validation remains necessary; avoid simultaneous editing in old/new UIs. Main branch, release assets, watchdog, serial reader and original MQTT callbacks are unchanged.
