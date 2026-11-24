"""Cross-feature tests: PR6 counters, PR7 metrics, PR8 historian share data safely."""
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone

from diagnostics.cycle_counter import CycleCounter
from diagnostics.circuit_telemetry import CircuitSample, derive
from diagnostics.history_store import HistoryStore
from diagnostics.mqtt_history import HistoryCollector
from diagnostics.mqtt_cycle_bridge import METRICS as COUNTERS, MQTTInput
from diagnostics.mqtt_circuit_bridge import METRIC_UNITS as CIRCUIT

BASE = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)


class CombinedDiagnosticsTests(unittest.TestCase):
    def test_unique_home_assistant_sensor_names(self):
        self.assertEqual(len(COUNTERS), 8)
        self.assertEqual(len(CIRCUIT), 6)
        self.assertFalse(set("HaierPi_PR6_" + x for x in COUNTERS) &
                         set("HaierPi_PR7_" + x for x in CIRCUIT))

    def test_shared_history_of_derived_and_counter_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            counters = CycleCounter(root / "counters.json")
            history = HistoryStore(root / "history.sqlite")
            try:
                for second, hz, df in [(0, 0, False), (30, 40, False),
                                       (60, 40, True), (90, 40, True),
                                       (120, 0, False)]:
                    result = counters.observe(BASE + timedelta(seconds=second),
                        compressor_hz=hz, defrost=df,
                        r141_fresh=True, r241_fresh=True)
                self.assertEqual(result["compressor_starts"], 1)
                self.assertEqual(result["defrost_starts"], 1)

                measurements = derive(CircuitSample(
                    twi=31, two=34, tao=2, tsat_ps_actual=-2.5,
                    tsat_pd_actual=32.6, td=47.1, ps_actual=0.6,
                    pd_actual=2.2, compressor_actual_hz=40,
                    compressor_target_hz=55),
                    r141_fresh=True, r241_fresh=True)

                collector = HistoryCollector(history, minimum_interval=1)
                a = "climate/haier/diagnostics/counters/compressor_starts"
                b = "climate/haier/diagnostics/pr7/water_delta_t"
                self.assertEqual(collector.discover({
                    "unique_id": "HaierPi_PR6_compressor_starts",
                    "state_topic": a}), a)
                self.assertEqual(collector.discover({
                    "unique_id": "HaierPi_PR7_water_delta_t",
                    "state_topic": b}), b)
                collector.receive(a, str(result["compressor_starts"]),
                                  timestamp=BASE, monotonic=100)
                collector.receive(b, str(measurements["water_delta_t"]),
                                  timestamp=BASE, monotonic=100)
                self.assertEqual(history.summary()["sample_count"], 2)
                p = history.export_csv(root / "combined.csv", "samples")
                self.assertIn("HaierPi_PR7_water_delta_t",
                              p.read_text(encoding="utf-8"))
            finally:
                history.close()

    def test_counter_unavailable_when_pump_frame_stale(self):
        source = MQTTInput()
        source.discover({"unique_id": "HaierPi_Compfact",
                         "state_topic": "pump/comp",
                         "value_template": "{{ value_json[1] | float }}"})
        source.discover({"unique_id": "HaierPi_Defrost",
                         "state_topic": "pump/defrost"})
        for block in source.health:
            source.availability(block, "online")
        source.update("pump/comp", "[55,40]", now=100)
        source.update("pump/defrost", "OFF", now=100)
        self.assertEqual(source.current(now=101), (40, False))
        source.availability("r141", "offline")
        self.assertIsNone(source.current(now=102))


if __name__ == "__main__":
    unittest.main()
