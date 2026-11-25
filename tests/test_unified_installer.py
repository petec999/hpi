"""Full install must fail without touching the core; use lightweight diagnostics."""
import os
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class FullInstallerSafetyTests(unittest.TestCase):
    def test_full_installer_intentionally_disabled(self):
        result = subprocess.run(["bash", str(ROOT / "install-all-safe.sh")],
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("DISABLED", result.stderr)
        self.assertIn("install-diagnostics-light.sh", result.stderr)

    def test_full_installer_contains_no_mutating_commands(self):
        source = (ROOT / "install-all-safe.sh").read_text()
        for dangerous in ("rm -rf", "systemctl stop", "sfdisk", "resize.f2fs",
                          "install-safe.sh", "haierpi-pr8"):
            self.assertNotIn(dangerous, source)


if __name__ == "__main__":
    unittest.main()
