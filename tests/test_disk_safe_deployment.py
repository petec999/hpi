"""Regression guards for low-space HaierPi deployments.

The real device has a 246 MB overlay root and a separately mounted /opt.
These checks ensure the dangerous full update fails before stopping core and
the lightweight deploy remains independent of /opt/haier mutations.
"""
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DiskSafetyTests(unittest.TestCase):
    def test_scripts_are_valid_bash(self):
        for name in ("install-safe.sh", "install-all-safe.sh",
                     "install-diagnostics-light.sh", "rollback-safe.sh"):
            with self.subTest(script=name):
                subprocess.run(["bash", "-n", str(ROOT / name)], check=True)

    def test_full_install_rejects_before_core_install(self):
        source = (ROOT / "install-all-safe.sh").read_text()
        self.assertIn("APP_REQUIRED_KB", source)
        self.assertIn("BACKUP_REQUIRED_KB", source)
        self.assertLess(source.index("Full upgrade refused BEFORE core changes"),
                        source.index('bash "$CORE_SCRIPT"'))

    def test_core_wrapper_checks_space_before_backup(self):
        source = (ROOT / "install-safe.sh").read_text()
        self.assertLess(source.index("BACKUP_NEED_KB"), source.index('tar -cpf "$BACKUP/app.tar"'))
        self.assertIn("Insufficient rollback space", source)

    def test_light_mode_never_invokes_core_installer(self):
        source = (ROOT / "install-diagnostics-light.sh").read_text()
        self.assertNotIn('bash "$CORE_SCRIPT"', source)
        self.assertNotIn("bash alpha13.sh", source)
        self.assertNotIn('rm -rf -- "$CORE"', source)
        self.assertIn("One venv and one diagnostics tree", source)
        self.assertIn("SPACE OK", source)
        self.assertIn('tar -tzf "$SNAP/previous.tar.gz"', source)
        self.assertIn("install_verify.py", source)


if __name__ == "__main__":
    unittest.main()
