# PR #6 — compressor and defrost counters (work in progress)

This is an **offline, read-only counter module**, not yet wired into the
HaierPi alpha13/Stable application's main.py, scheduler or MQTT Discovery.
Do not install this branch as a drop-in replacement for a working controller.

## Signals needed
- Actual compressor frequency in Hz from the correctly mapped R241 field.
  Use PR #2's actual/target frequency correction before integration.
- Explicit defrost flag from R141, not guessed from refrigerant temperatures.
- Separate freshness checks for R141 and R241 (PR #4).

## Semantics
- Count an OFF -> ON compressor transition only between consecutive fresh
  samples, above the configured compressor Hz threshold.
- Count defrost OFF -> ON based on the explicit flag.
- Runtime is accumulated only when both ends of an interval indicate ON.
  State transition instants are unknown, so runtime is deliberately conservative.
- Never invent starts after service restart, missing data, nonmonotonic
  timestamps or a gap beyond max_gap_seconds (default 180 seconds).
- An active cycle interrupted by a telemetry gap cannot be measured in full.
- Daily figures use the date of the timezone-aware timestamp supplied by the
  host. The integrator must use a consistent timezone (Europe/Warsaw for the
  target installation); DST transitions and midnight splits need integration tests.

## Persistence
Versioned JSON written atomically after each observation. Default path is
**not hard-coded**; the integrator must choose a location outside directories
removed by the alpha13 installer, e.g. /var/lib/haierpi/cycle_counters.json,
create it with suitable permissions and back it up. Only the current day's
totals are persisted. Previous days are overwritten: longer history is PR #8.
A restart loads totals but intentionally loses the previous active-cycle
baseline. This may undercount runtime and completed-cycle lengths.

## Planned Home Assistant MQTT Discovery
Proposed sensors: daily starts, daily compressor running seconds, completed
cycles, last completed cycle seconds, daily defrost starts, defrost running
seconds, completed defrosts and last defrost seconds. Units/state classes
must be chosen to avoid duplicate energy/statistical claims. MQTT topics and
discovery configuration are **not implemented yet**.

## Run unit tests
python3 -m unittest discover -s tests -p 'test_cycle_counter_pr6.py' -v

## Integration gate
Before enabling this module in HaierPi verify alpha13 and Stable source layouts,
actual refresh cadence, explicit defrost bit semantics, MQTT reconnect behavior,
persistence and timezone handling on real hardware. No heating commands,
Modbus layouts or existing MQTT entity IDs should be changed.
