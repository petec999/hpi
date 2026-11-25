# Legacy full installer is disabled

The `install-all-safe.sh` entrypoint is disabled deliberately. It does not
modify the HaierPi controller and exits with code 2.

For cycle and refrigeration diagnostics only use
`install-diagnostics-light.sh`, which checks free space, saves a rollback
snapshot, retires the old SQLite historian and starts only
`haierpi-cycles.service` and `haierpi-circuit.service`.

## NanoPi-specific cautions

- Root uses RAM-backed OverlayFS; `/etc/systemd/system` changes are temporary.
- `/opt` is persistent F2FS and has been nearly full. Never delete rescue
  backups just to force a deployment.
- No historical SQLite writer should run on this device. Long-term plots
  belong in Home Assistant's recorder.
- Cycle counters reset at service restart; no SD-backed JSON snapshots.
- If a startup migration fails, inspect saved logs and rollback snapshot
  before attempting another install.
- Do not reboot until diagnostics service persistence has been separately
  addressed, if automatic restart is required.
