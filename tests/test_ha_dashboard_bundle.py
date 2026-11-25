"""PR8 SQLite reporting utility checks; HA UI belongs in home-iot-telemetry."""
import ast
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
PR8 = ROOT / "tools" / "pr8_report.py"


class PR8ReportTests(unittest.TestCase):
    def test_pr8_report_syntax_and_help(self):
        ast.parse(PR8.read_text(encoding="utf-8"))
        proc = subprocess.run(
            [sys.executable, str(PR8), "--help"],
            text=True, capture_output=True, check=True)
        self.assertIn("--samples-csv", proc.stdout)
        self.assertIn("--events-csv", proc.stdout)

    def test_hpi_does_not_bundle_home_assistant_ui(self):
        self.assertFalse((ROOT / "homeassistant" / "haier-diagnostyka-view.yaml").exists())


if __name__ == "__main__":
    unittest.main()
