"""Offline unified installer success and rollback tests."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]


class UnifiedInstallerTests(unittest.TestCase):
    def simulate(self, fail):
        with tempfile.TemporaryDirectory(prefix="hpi-unified-") as td:
            t = Path(td)
            pkg = t / "package"
            pkg.mkdir()
            for name in ("install-all-safe.sh", "install-safe.sh",
                         "rollback-safe.sh", "alpha13.sh", "1.4.5_alpha13.tar.gz"):
                shutil.copy(ROOT / name, pkg / name)
            shutil.copytree(ROOT / "deployment", pkg / "deployment")
            shutil.copytree(ROOT / "diagnostics", pkg / "diagnostics")
            (pkg / "mock-core.sh").write_text(
                '#!/bin/bash\nmkdir -p "$HPI_BACKUP_ROOT/core-snapshot"\n'
                'touch "$HPI_BACKUP_ROOT/core-snapshot/app.tar"\n'
                'echo new > "$HPI_SIM_ROOT/core-status"\n')
            (pkg / "mock-restore.sh").write_text(
                '#!/bin/bash\necho old > "$HPI_SIM_ROOT/core-status"\n')
            (pkg / "mock-verify.py").write_text("pass\n")
            (t / "core-status").write_text("old\n")
            (t / "opt").mkdir()
            (t / "opt" / "haier").mkdir()
            (t / "opt" / "haier" / "main.py").write_text("# simulated core\n")
            (t / "etc" / "systemd" / "system").mkdir(parents=True)
            (t / "state").mkdir()
            (t / "state" / "haier.active").touch()
            src = pkg / "install-all-safe.sh"
            s = src.read_text()
            replacements = {
                '"/opt/$key"': f'"{t}/opt/$key"',
                '"/etc/systemd/system/$key.service"':
                    f'"{t}/etc/systemd/system/$key.service"',
                '"/etc/$key.env"': f'"{t}/etc/$key.env"',
                '"$ROOT/install-safe.sh"': '"$ROOT/mock-core.sh"',
                '"$ROOT/rollback-safe.sh"': '"$ROOT/mock-restore.sh"',
                '"$ROOT/diagnostics/install_verify.py"': '"$ROOT/mock-verify.py"',
            }
            for old, new in replacements.items():
                self.assertIn(old, s)
                s = s.replace(old, new)
            src.write_text(s)
            env_file = t / "mqtt.env"
            env_file.write_text(
                "HPI_MQTT_HOST=localhost\nHPI_TOPIC=climate/haier\n")
            env_file.chmod(0o600)
            bin_dir = t / "bin"
            bin_dir.mkdir()
            py = bin_dir / "fakepython"
            py.write_text(
                '#!/bin/bash\n'
                'if [[ "$1" == -m && "$2" == venv ]]; then '
                'mkdir -p "$3/bin"; cp "$0" "$3/bin/python"; exit 0; fi\n'
                'if [[ "$1" == -m && "$2" == pip ]]; then exit 0; fi\n'
                'if [[ "$1" == -c ]]; then exit 0; fi\n'
                'if [[ "$1" == *mock-verify.py ]]; then exit 0; fi\n'
                'exec "' + sys.executable + '" "$@"\n')
            py.chmod(0o755)
            ctl = bin_dir / "systemctl"
            ctl.write_text(textwrap.dedent("""#!/bin/bash
set -e
key="${@: -1}"
key="${key%.service}"
case "$1" in
 is-active) [[ -f "$HPI_SIM_ROOT/state/$key.active" ]];;
 is-enabled) [[ -f "$HPI_SIM_ROOT/state/$key.enabled" ]];;
 stop) rm -f "$HPI_SIM_ROOT/state/$key.active";;
 start) touch "$HPI_SIM_ROOT/state/$key.active";;
 enable) if [[ "$HPI_TEST_FAIL" == 1 && "$key" == haierpi-pr8 ]]; then exit 3; fi
         touch "$HPI_SIM_ROOT/state/$key.enabled"
         if [[ "$2" == --now ]]; then touch "$HPI_SIM_ROOT/state/$key.active"; fi;;
 disable) rm -f "$HPI_SIM_ROOT/state/$key.enabled";;
 daemon-reload) exit 0;;
 *) exit 1;;
esac
"""))
            ctl.chmod(0o755)
            env = dict(os.environ)
            env.update({
                "PATH": str(bin_dir) + ":" + env["PATH"],
                "HPI_SIM_ROOT": str(t),
                "HPI_TEST_FAIL": str(int(fail)),
                "HPI_SERVICE": "haier",
                "HPI_BACKUP_ROOT": str(t / "backups"),
                "HPI_APP_DIR": str(t / "opt" / "haier"),
                "HPI_DATA_DIR": str(t / "data"),
                "HPI_DIAGNOSTICS_ENV": str(env_file),
                "HPI_PYTHON": str(py),
                "HPI_CHECK_SECONDS": "0",
            })
            result = subprocess.run(
                ["bash", str(src)], cwd=pkg, env=env,
                capture_output=True, text=True, timeout=45)
            self.assertEqual(result.returncode != 0, fail,
                             result.stdout + result.stderr)
            if fail:
                self.assertEqual((t / "core-status").read_text().strip(), "old")
                self.assertFalse(any(p.name.startswith("haierpi-pr") for p in (t / "opt").iterdir()))
            else:
                self.assertEqual((t / "core-status").read_text().strip(), "new")
                self.assertEqual(len(list((t / "opt").iterdir())), 4)

    @unittest.skipUnless(os.geteuid() == 0, "requires root")
    def test_success(self):
        self.simulate(False)

    @unittest.skipUnless(os.geteuid() == 0, "requires root")
    def test_rollback_on_pr8_failure(self):
        self.simulate(True)


if __name__ == "__main__":
    unittest.main()
