# HaierPi — lightweight cycle and circuit diagnostics

This development branch provides **read-only MQTT diagnostics** for an existing
HaierPi. It does **not** reinstall or modify the original `/opt/haier`
application. There is **no SQLite historian** and no historical data writer.

## Services and memory

- `haierpi-cycles.service` — compressor starts, run time, cycle lengths and defrost counters.
- `haierpi-circuit.service` — six refrigeration and water-circuit measurements.
- Both services read MQTT only, publish sensor values, and do not send heat-pump control commands.
- Cycle counters live **only in RAM**. A service restart/reboot resets today's
  counts; MQTT/HA recorder can maintain longer-term graphs outside the NanoPi.
- No JSON state files and no SQLite database are written by these services.
- There are still MQTT publications to the broker; this is network traffic, not an SD write.

The internal HA MQTT `unique_id` values containing old development identifiers
are intentionally **kept for compatibility with the existing 14 entity IDs**.
Renaming those identifiers would duplicate/replace sensors and break dashboards.
Device display names and systemd unit names are descriptive instead.

## Low-space NanoPi / OverlayFS

The actual machine uses a RAM-backed overlay root, with `/opt` on a small F2FS
filesystem (previously only ~33 MiB free). Installing code into `/opt` writes
to SD **once during deployment**; no recurring diagnostic data is written there.
The existing rescue backup under `/opt/haierpi-rescue` is never deleted.

The only supported diagnostics entrypoint is:

```sh
sudo bash install-diagnostics-light.sh
```

It stages in RAM, checks space, takes a rollback snapshot, stops/retire legacy
numeric-name services (including the old SQLite historian), starts only the two
new services, and verifies MQTT availability. On failure it attempts to restore
the previous diagnostic services and code. It never touches the core HaierPi.
**Do not run it unless the NanoPi has sufficient space for a safe backup and
installation**; the script will refuse if its preflight fails.

`install-all-safe.sh` is explicitly DISABLED. No full core upgrade is allowed
by this diagnostics bundle. The original core wrapper remains in the repository
for separate, carefully reviewed maintenance only.

## Important: OverlayFS service persistence

The NanoPi's `/etc` changes occur in RAM and will **not** survive a reboot.
The lightweight installer does NOT override that protection, which means
its dynamically installed systemd units are only guaranteed for the current boot.
Before any reboot, plan a **one-time** persistence arrangement that respects
the read-only root design. Do not remount the SD read/write just to continuously
log diagnostics.

## Home Assistant

The 8 cycle sensors and 6 refrigeration sensors are discovered automatically.
The UI dashboard belongs in the separate repository:
https://github.com/petec999/home-iot-telemetry/tree/main/home_assistant/dashboards

Graph history is the responsibility of Home Assistant, **not** the NanoPi.

## Source and safety

- `diagnostics/mqtt_cycle_bridge.py` and `diagnostics/cycle_counter.py`:
  RAM counters and MQTT Discovery.
- `diagnostics/mqtt_circuit_bridge.py`: derived sensor values.
- `diagnostics/derive_mqtt_env.py`: read MQTT credentials from existing
  `/opt/config.ini` without printing secrets.
- `install-diagnostics-light.sh`: disk-safe two-service migration.
- `tests/`: unit, simulated MQTT, and safety regression tests.
- `docs/`: engineering notes.

This project preserves no SQLite history, does not touch the heat-pump control
registers, and does not add new background writes to the SD.
