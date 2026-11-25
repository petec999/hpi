"""Checks that the published HA view references the confirmed live entity IDs."""
import ast
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
VIEW = ROOT / "homeassistant" / "haier-diagnostyka-view.yaml"
PR8 = ROOT / "tools" / "pr8_report.py"

PR6 = (
    "compressor_starts_today", "compressor_run_today",
    "completed_compressor_cycles_today", "last_compressor_cycle",
    "defrost_starts_today", "defrost_run_today",
    "completed_defrost_cycles_today", "last_defrost_cycle",
)
PR7 = (
    "co_water_delta_t", "refrigerant_saturation_lift",
    "ambient_evaporation_approach", "discharge_condensing_gap",
    "refrigerant_pressure_delta", "compressor_frequency_deviation",
)


class PanelTest(unittest.TestCase):
    def test_panel_contains_all_confirmed_14_entities(self):
        doc = VIEW.read_text(encoding="utf-8")
        for suffix in PR6:
            with self.subTest("PR6 " + suffix):
                self.assertIn("sensor.haierpi_diagnostics_" + suffix, doc)
        for suffix in PR7:
            with self.subTest("PR7 " + suffix):
                self.assertIn("sensor.haierpi_advanced_diagnostics_" + suffix, doc)
        self.assertIn("title: Diagnostyka techniczna", doc)
        self.assertIn("type: history-graph", doc)

    def test_panel_does_not_change_controls(self):
        doc = VIEW.read_text(encoding="utf-8")
        self.assertNotIn("type: button", doc)
        self.assertNotIn("perform-action:", doc)
        self.assertNotIn("service:", doc)

    def test_pr8_report_syntax_and_help(self):
        ast.parse(PR8.read_text(encoding="utf-8"))
        proc = subprocess.run([sys.executable, str(PR8), "--help"],
                              text=True, capture_output=True, check=True)
        self.assertIn("--samples-csv", proc.stdout)
        self.assertIn("--events-csv", proc.stdout)


if __name__ == "__main__":
    unittest.main()
