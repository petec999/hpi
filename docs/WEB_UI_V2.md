# Web UI v2 — experimental preview on HaierPi 1.4.5_3

The original interface and control code remain unchanged. The new authenticated routes are GET `/v2/`, GET `/v2/api/state` and POST `/v2/api/control`. The installer requires the existing watchdog v2 marker and a recognized authenticated Flask route. It refuses unexpected sources or read-only mounts, backs up main.py and restarts haier once; the shell wrapper restores the backup on startup failure. It does not alter mount flags, upstream archives, HA, MQTT topics, Modbus or control functions.

Data is limited to an explicit allowlist of cached source measurements, not the full status dictionary. R141/R241 freshness gates each measurement; derived differences require the relevant frames. The panel distinguishes MQTT broker connectivity from HA readback. No extra RS485 or MQTT requests, no database, no CDN; chart history is limited to ten minutes in the browser. Missing values remain unavailable. The hydraulic schematic is generic. This preview does not expose sidecar counters, pressure data, historical charts, or full settings yet.

## Installation on existing 1.4.5_3

Download the two source files at a reviewed commit, put the Python file in `tools/` next to the shell wrapper. Run `bash install-web-ui-v2.sh --dry-run` first, then `bash install-web-ui-v2.sh`. Open the normal HaierPi address, log in using the original UI, and append `/v2/`. Existing WWW remains available at `/`.

Only deploy on a trusted local network or VPN. The new endpoints reuse the existing login system; known upstream authentication/session issues are not fixed by this preview. Never publish the controller directly to the Internet.

Rollback: use the printed wrapper backup path, restore it to /opt/haier/main.py preserving permissions, then restart haier. Do not restore an old backup over unrelated subsequent changes. Future upstream upgrades may remove the patch.

CI checks synthetic Flask authorization, GET-only telemetry API, filtering, missing/stale data, field mapping, and applies the patch to the SHA-pinned Stable archive with the existing watchdog installer. It does not run the actual controller or validate real sensor data. Live validation is required. Published v1.4.5_3 assets and main remain unchanged.

## Mobile control preview

The bottom mobile navigation remains visible while scrolling. The new control cards expose PCH and PDHW on/off, CH and DHW target temperatures in 0.5°C steps and Eco/Quiet/Turbo profile. The intentionally conservative preview limits are 20–45°C for the CH setting and 35–55°C for DHW; original UI retains its full existing ranges. CH uses the existing heat target/curve handling (not a direct forced outlet temperature); changing DHW target does not enable DHW. Advanced configuration, scheduler, curve calculator and historical charts open the original UI.

Commands call the existing statechange, new_tempchange and new_presetchange handlers, preserve direct-mode curvecalc behavior and do not call Modbus directly. The POST endpoint requires existing login, session CSRF token, matching Origin, explicit command allowlist, expected previous value, both fresh frames and a nonblocking single-command lock. No automatic resend. The browser distinguishes pending from observed matching cached state, which is **not** independent hardware confirmation. Existing R101/R201 data lack per-block freshness; actual control and safety behavior must be verified on-device. Existing upstream authentication issues remain; LAN/VPN only.

The installer now recognizes and upgrades the exact original v2 preview block from commit 7961a18, or installs on a clean compatible 1.4.5_3. Unknown modifications fail closed. Always download both updated installer files from the same commit. A dry run validates the migration; actual deployment restarts haier once. No device changes have been performed by CI.
