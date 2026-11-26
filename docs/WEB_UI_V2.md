# Web UI v2 — experimental preview on HaierPi 1.4.5_3

The original interface and control code remain unchanged. The new authenticated GET-only routes are `/v2/` and `/v2/api/state`. The installer requires the existing watchdog v2 marker and a recognized authenticated Flask route. It refuses unexpected sources or read-only mounts, backs up main.py and restarts haier once; the shell wrapper restores the backup on startup failure. It does not alter mount flags, upstream archives, HA, MQTT topics, Modbus or control functions.

Data is limited to an explicit allowlist of cached source measurements, not the full status dictionary. R141/R241 freshness gates each measurement; derived differences require the relevant frames. The panel distinguishes MQTT broker connectivity from HA readback. No extra RS485 or MQTT requests, no database, no CDN; chart history is limited to ten minutes in the browser. Missing values remain unavailable. The hydraulic schematic is generic. This preview does not expose sidecar counters, pressure data, historical charts, settings or control commands yet.

## Installation on existing 1.4.5_3

Download the two source files at a reviewed commit, put the Python file in `tools/` next to the shell wrapper. Run `bash install-web-ui-v2.sh --dry-run` first, then `bash install-web-ui-v2.sh`. Open the normal HaierPi address, log in using the original UI, and append `/v2/`. Existing WWW remains available at `/`.

Only deploy on a trusted local network or VPN. The new endpoints reuse the existing login system; known upstream authentication/session issues are not fixed by this preview. Never publish the controller directly to the Internet.

Rollback: use the printed wrapper backup path, restore it to /opt/haier/main.py preserving permissions, then restart haier. Do not restore an old backup over unrelated subsequent changes. Future upstream upgrades may remove the patch.

CI checks synthetic Flask authorization, GET-only API, filtering, missing/stale data, field mapping, and applies the patch to the SHA-pinned Stable archive with the existing watchdog installer. It does not run the actual controller or validate real sensor data. Live validation is required. Published v1.4.5_3 assets and main remain unchanged.
