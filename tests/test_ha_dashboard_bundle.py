"""Guard against SQLite activity and unclear installed systemd names."""
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class RamOnlyDeploymentTests(unittest.TestCase):
    def test_cycle_counter_is_ram_only_in_live_bridge(self):
        source = (ROOT / "diagnostics/mqtt_cycle_bridge.py").read_text()
        self.assertIn("counters = CycleCounter()", source)
        self.assertNotIn("HPI_COUNTER_FILE", source)

    def test_deployment_uses_readable_names_not_numeric_legacy_units(self):
        install = (ROOT / "install-diagnostics-light.sh").read_text()
        self.assertIn("UNITS=(haierpi-cycles haierpi-circuit)", install)
        self.assertIn("LEGACY_UNITS=", install)
        self.assertIn("--no-db", install)
        self.assertFalse((ROOT / "deployment/haierpi-pr8.service").exists())
        self.assertTrue((ROOT / "deployment/haierpi-cycles.service").exists())
        self.assertTrue((ROOT / "deployment/haierpi-circuit.service").exists())

    def test_no_home_assistant_dashboard_embedded_in_hpi(self):
        self.assertFalse((ROOT / "homeassistant" / "haier-diagnostyka-view.yaml").exists())


if __name__ == "__main__":
    unittest.main()
