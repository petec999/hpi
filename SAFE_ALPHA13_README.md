# HaierPi 1.4.5 alpha13 — safe personal update

This branch contains a standalone, locally preflighted update script. It is **not an upstream release** and has not been tested on a real heat pump.

## Download and check (no installation yet)

```sh
curl -fsSL https://raw.githubusercontent.com/petec999/hpi/safe-alpha13-bundle/HaierPi_alpha13_SAFE_installer.sh -o haierpi-safe.sh
sha256sum haierpi-safe.sh
sudo bash haierpi-safe.sh --check
```

Expected SHA256: `cc10b0cf68c3652d9b14a42a8672b1d2eae2f2ca7ebcf1c05f0f5d44a0ce5033`.

**Only if the preflight prints PASS:**

```sh
sudo bash haierpi-safe.sh --install
```

## Emergency rollback

```sh
sudo bash /opt/haier-safe-backups/LATEST/rollback.sh
```

The installer saves the original seven Python files and a standalone rollback script in a timestamped, root-only directory under `/opt/haier-safe-backups/`. It also attempts automatic rollback if the systemd service fails to start or crashes in the first 30 seconds after the update. An active service does not prove that all RS485 readings have been verified; check the HaierPi UI and Home Assistant after installation.

## Scope

- Signed U2 12-bit negative temperatures: 4095 → 4096 (6 decoders / 10 locations).
- Correct compressor actual/target frequency mappings in MQTT Discovery.
- Preserve sign of superheat/subcooling differences.
- Independent R141 and R241 frame freshness, 180-second timeout, HA availability gating.
- Leaves `static/`, `templates/`, `/opt/config.ini`, and MQTT retained legacy entity definitions untouched.
- **Does not include the unverified legacy MQTT sensor cleanup PR #3.**

### Safety limitations

The preflight expects a compatible existing HaierPi alpha13 source layout and fails closed on mismatch. It changes no heating setpoints, GPIO settings or Modbus control commands. Backups are automatic and retained. Only local synthetic-fixture tests have been performed: preflight, installation, manual rollback, and automatic rollback on simulated service start failure. Use at your own risk and inspect your heat pump after installation.

The script downloads a pinned, SHA256-verified helper from commit `da0372290be8dd85ae7b29643b9a1a97dd5d7512` if that helper is not alongside it. For offline installation use the downloadable ZIP supplied in the ChatGPT conversation, which bundles both files.
