# HaierPi diagnostics: reboot-safe startup on read-only OverlayFS

The NanoPi uses a read-only F2FS lower root with a RAM-backed OverlayFS.
One-time diagnostics code is stored in `/opt/haierpi-diagnostics` (persistent).
Changes made to `/etc`, including user records and systemd unit definitions,
**disappear at reboot**.

This procedure was tested on the owner's NanoPi on **25 November 2026**.
After reboot the original `haier`, `haierpi-cycles`, `haierpi-circuit`,
and `dropbear` services all reported `active`, while `/` remained overlay.
The F2FS resize is **a separate, uncompleted task**.

## Boot sequence

1. Base DietPi systemd starts the original `dietpi-postboot.service`.
2. Its persistent `/boot/dietpi/postboot` calls `/opt/haierpi-startup/start.sh`
   after the existing `# END HAIERPI SCP` block and before `exit 0`.
3. The one-shot script recreates `haierpi_diag` as UID/GID 998 **in RAM**,
   subject to collision checks (this UID is machine-specific).
4. It derives MQTT credentials from the existing persistent `/opt/config.ini`,
   into RAM-only `/etc/haierpi-diagnostics.env` (mode 0600).
5. It restores two systemd unit files into RAM-backed `/etc/systemd/system`
   and enables/starts them. The application and venv remain under `/opt`.

This does not change the original HaierPi controller or create any periodic
SD-card history writes. Counters are RAM-only and **reset at reboot**.
The Home Assistant recorder stores history elsewhere.

## Persisted files (one-time installation)

Copy `deployment/haierpi-startup/start.sh` to
`/opt/haierpi-startup/start.sh` (root-owned, executable, mode 0700).
Copy `deployment/haierpi-cycles.service` and
`deployment/haierpi-circuit.service` to that directory (root-owned,
mode 0600). Do not store passwords or `haierpi-diagnostics.env` there.

The live device already has these files and an existing boot hook; **do not
run a second install blindly**.

## Existing one-line DietPi hook

The following block was added once after `# END HAIERPI SCP` in the
existing persistent `/boot/dietpi/postboot`:

```sh
# BEGIN HAIERPI DIAGNOSTICS
if [ -x /opt/haierpi-startup/start.sh ]; then
    /opt/haierpi-startup/start.sh ||
        echo "WARNING: HaierPi diagnostics startup failed" >&2
fi
# END HAIERPI DIAGNOSTICS
```

A backup of the original is stored as
`/boot/dietpi/postboot.before-haierpi-startup`. Do not append this block
again. The original `haier.service` was not modified.

## Verification

Before any restart, verify there is physical/serial recovery and an external
backup. Check syntax and status:
```sh
bash -n /opt/haierpi-startup/start.sh
bash -n /boot/dietpi/postboot
systemctl is-active haier haierpi-cycles haierpi-circuit
```

After restart:
```sh
systemctl is-active haier haierpi-cycles haierpi-circuit dropbear
ss -ltnp | grep ':22 '
findmnt -T / -o TARGET,SOURCE,FSTYPE
```

If the hook fails, inspect `systemctl status dietpi-postboot`, its
journal, `systemctl status haierpi-cycles haierpi-circuit`, account UID/GID
and whether `/opt` is mounted. Never persist MQTT credentials on `/boot`.
