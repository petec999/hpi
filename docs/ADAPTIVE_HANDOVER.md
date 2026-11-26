# HaierPi Adaptive Learning — handover / continuation

Updated: 2026-11-26. Read this file before continuing work in a new conversation. Technical project notes only: no household history, secrets, addresses, credentials or raw device logs are included.

## Goal

Replace the existing CO anti-cycling preset/FLimit policy with an opt-in adaptive supervisor that actually controls the pump and learns online. Use all six Quiet/Eco/Turbo × FLimit OFF/ON combinations. Reduce cycling while tracking the existing water setpoint. Preserve native heat demand, heating curve, defrost, DHW/service priorities and factory protection. No forced compressor start/stop, no raw register control beyond existing core handlers. No SQLite; minimise storage writes.

## Repository and tested versions

- Repository: petec999/hpi, separate branch `feature/adaptive-learning`. Do not modify upstream or main blindly.
- Base integrated preview: `18bf0fe01292e937fc3d17c207a660340195f8e2` (includes earlier `3d45eb0dd8ce1e3f2ce5887b48fdfbab4f345f7f`).
- Learning preview: `8eba0fb1cbc1484860b2c02365b3647a124c3d1b`; GitHub Actions run 45825533042 passed Python 3.9/3.11 and Stable integration/upgrade tests. User installed the preview; fresh four-frame integration confirmed in device journal. Actual Auto control/learning not yet confirmed.
- WWW navigation fix: `dcb0a28c0c159f24624a9efb560d0845b961ff69`. Run 45830790435 status at handover: completed/success. Not confirmed installed. Replaces incorrect /curvecalc link with original panel /; other links /scheduler, /settings, /parameters, /charts are real template routes. Exact location of curve controls in original UI not yet verified.
- Keep GPIO/RS485 initial receive and readback fixes, MQTT reconnect/PUBACK and HA watchdog v2, diagnostic sidecars, existing configuration and original WWW. No clean reinstall.
- See docs/INTEGRATED_ADAPTIVE_PREVIEW.md, docs/ADAPTIVE_MODULATION.md, docs/ADAPTIVE_LEARNING.md.

## Current issue and next immediate step

Selecting Auto — experimental then applying in /v2/ appears to revert to Legacy after refresh. Device log confirms valid four-frame data and no active pump error, but original `presetautochange=manual` and `flimit=manual`. Runtime.choose explicitly requires both to be `auto`, as well as normal outdoor zone, no priority operation/error, valid readback and target within 1 K of computed curve. This was a known activation blocker in the installed learning preview. The next revision removes dependence on the two legacy settings, preserves their values, and surfaces specific activation blockers and actual owner in the new UI. Other causes have not been excluded; actual /v2/api/state is still needed if issue persists. Do not claim Auto is active until verified. Curve configuration migration is still pending inspection of the original templates; the navigation fix alone does not provide editing in v2. No need to restart merely for a navigation fix. Legacy is intentionally default after each service restart; memory persists separately. A failed runtime command or prolonged invalid telemetry disarms to Manual, not Legacy.

## Algorithm details

- Tick every 30 s; four complete fresh frames R101/R141/R201/R241 (max age 60 s); actual GPIO readback must be string "0"/"1". Supply target from actual pump readback, not simply heating curve. 150-second median trends; three-minute base forecast. Up: release FLimit first, then raise preset. Down: enable FLimit first, then reduce preset. Only one output at a time; no fixed power ranking.
- Confirm normal shortage 120 s, urgent shortage 60 s; base downward confirmation 90 s; settling 180 s; startup hold 300 s with limited early/urgent paths; stable probe after 900 s. Restore failed observed reduction and block retry 30 min.
- Learning only from confirmed Auto reductions. Store recent response (frequency and temperature error), score and observation count by outdoor 5 K band, water target 3 K band and transition. At least 3 observations in same context before adapting. Down confirm 60–120 s, surplus threshold 0.4–0.8 K, early threshold 0.7–1.1 K, forecast 2.5–3.5 min. Upward response and factory protections unchanged. Interrupted trials excluded; this is bounded online adjustment, not a causal model or proof of savings. No learning in Shadow.
- Persistent file /opt/haier/.adaptive-learning.json, maximum 128 contexts, atomic save at most every 6 hours per process, first save can be immediate. RAM if storage unavailable. Unsaved observations may be lost on restart. The UI shows learning observations/contexts and current tuning.

## Installation

Use only a pinned verified commit; check CI and preserve backup. Known tested learning installer:

```bash
REF=8eba0fb1cbc1484860b2c02365b3647a124c3d1b
curl -fsSL "https://raw.githubusercontent.com/petec999/hpi/$REF/install-adaptive-preview.sh" -o /tmp/install-adaptive-preview.sh && bash /tmp/install-adaptive-preview.sh "$REF" --apply
```

Use --dry-run to validate without writes. Installer stages core GPIO/MQTT/WWW and embedded modules, backs up files, restarts haier, checks independently renewed four-frame sets and valid snapshot, restores on failure. No automatic remount. After restart open /v2/ and explicitly choose Auto once prerequisites met. Check MQTT watchdog separately.

## Verification and follow-up

1. Confirm real Auto status via authenticated /v2/api/state (adaptive.control, ready, fault, reason, pending, mode, relay, learning) and filtered journal; avoid exposing credentials. Verify actual preset and GPIO readback after proposals. Check MQTT watchdog and HA telemetry separately.
2. Collect normal heating history for 48–72 h after activation, without changing heating curve or unrelated settings unless comfort/safety requires it. Export HA history, local learning JSON and relevant journal observations privately. Do not publish raw home telemetry. Example local read-only commands:
   ```bash
   journalctl -u haier --since "3 days ago" --no-pager | grep -E 'Adaptive (proposal issued|learning observation|modulation disarmed)'
   test ! -f /opt/haier/.adaptive-learning.json || cat /opt/haier/.adaptive-learning.json
   ```
3. Compare cycle lengths/start counts, frequency, Two vs confirmed target, defrost exclusions, successful and failed reductions, learned parameters. No claim that cycling is eliminated: minimum physical capacity may exceed building demand.
4. Prior offline replay was exploratory; do not infer savings or causal prevention of stops. Hardware validation of live Auto and learning remains open.
5. Future enhancements: richer export and HA visibility, explicit UI blockers, robust retention/recovery and bounded learned tuning from real traces. Preserve all prior core fixes and test new commits in isolation.

Follow-up: Adaptive ownership no longer requires Legacy Manual/Auto settings to be changed. Curve navigation now links directly to the verified configuration section, and v2 has an authenticated recalculation button. Full curve editor remains the existing settings form. Check CI and live device before claiming success.

Full WWW v2 editor added: 14 manual points, manual/static/auto curve mode, slope/shift/gain, manual plot, explicit save/cancel. Reads existing SETTINGS fields; writes only curve keys with atomic replacement, conflict detection and reload via Stable loadconfig. Direct mode remains read-only in editor. Existing scheduled calculation applies changes; live installation still to validate. No automatic adjustment of curve by Adaptive.

Status display follow-up: a stopped compressor now shows `Postój sprężarki – oczekiwanie na wznowienie ogrzewania`; Auto remains selected and resumes automatically. Invalid data and requested zero with actual running have distinct messages. The policy's original reason and risk fields remain unchanged; WWW uses reason_pl. Installation restarts the service, so select Auto again after restart.

Idle startup preparation (Auto only): with CH enabled, normal outdoor zone, no protection/priority/mismatch, two distinct fresh compressor frames with both actual and requested Hz=0, prepare Quiet + FLimit. Enable relay first if necessary and confirm each individual command using existing readback. Shadow proposes only. No heat-demand or setpoint writes, no learning from stopped transitions. A native start can occur independently; no guaranteed quiet startup if the stop is shorter than confirmation. Hardware validation pending.

Field verification 26 Nov: normal idle has pch=on, ch_heating=off, demand=1 and actual/requested Hz=0. Stable GetParametersNEW derives pch from R101 bits 0/2 with cooling bit clear. Idle eligibility now checks those raw enable bits plus pch, not the active heating indicator. Regression test matches observed state; running policy still requires ch_heating. No private log content stored.

Current Twi-v2 policy supersedes earlier supply-centric assumptions: confirmed installation assumption STOP at Twi=target+5 K; display margin and trend. Reduction tracks return surplus and forecast, default 1.5 K surplus and 1 K warning margin; Two corroborates shortages only. All margins provisional, no forced stops or safety bypass. Old learning file retained untouched; new schema 2 stored separately at /opt/haier/.adaptive-learning-twi-v2.json; learns return trend and return error. No prior history validation of exact STOP threshold; user confirmed assumption, device validation pending.

Return forecast uses latest three-sample median as its starting value, full 150 s robust trend for projection. This avoids lag from using the entire-window median as the starting temperature. Added timing assertion on a rising-return trace and a current-return near-stop guard test.


## Passive hysteresis observer v1

The observer runs in every owner mode, before the Legacy early return. It never writes a pump command or changes regulator thresholds. It accepts completed requested-frequency (Fset) cycles only with CH enabled, demand present, normal zone, valid fresh telemetry, unchanged actual setpoint/preset/relay/owner, at least five minutes of observed idle and run, and two minutes of confirmed idle after STOP. Defrost, DHW, errors, priority operations and gaps invalidate in-flight cycles. Events record before/after temperature offsets and UTC epoch observation time, not exact firmware event times. Estimates are medians of sampled bracket midpoints, with MAD and median bracket width. Compare Twi/Two; no automatic sensor selection or threshold activation. Contexts are separated by exact target and outputs, so changing weather/curve can slow accumulation. At least 20 matching cycles is a review milestone, not proof.

Persistent bounded store: /opt/haier/.adaptive-hysteresis-v1.json (128 most recent cycles, atomic writes no more than once per five minutes; unsaved cycles can be lost on restart). In-flight cycles are never restored across reboot. WWW v2 and adaptive.hysteresis API expose counts, collection start, most recent observed context change and estimates. This is sampled telemetry, not a complete audit trail; changes between samples may be missed. Legacy with fixed preset and FLimit is recommended for initial observation. Historical HA import and automatic use of learned thresholds are not part of v1.
