"""Combined RAM-only cycle + read-only refrigeration circuit test."""
import unittest
from datetime import datetime, timedelta, timezone
from diagnostics.cycle_counter import CycleCounter
from diagnostics.circuit_telemetry import CircuitSample, derive
from diagnostics.mqtt_cycle_bridge import METRICS as COUNTERS, MQTTInput
from diagnostics.mqtt_circuit_bridge import METRIC_UNITS as CIRCUIT

BASE = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)


class CombinedDiagnosticsTests(unittest.TestCase):
    def test_unique_home_assistant_sensor_names(self):
        self.assertEqual(len(COUNTERS), 8)
        self.assertEqual(len(CIRCUIT), 6)
        self.assertFalse(set("HaierPi_PR6_" + x for x in COUNTERS) &
                         set("HaierPi_PR7_" + x for x in CIRCUIT))

    def test_ram_cycles_and_circuit_derivations(self):
        c = CycleCounter()  # no file path: live service never writes counters
        for second, hz, df in [(0, 0, False), (30, 40, False),
                               (60, 40, True), (90, 40, True),
                               (120, 0, False)]:
            result = c.observe(BASE + timedelta(seconds=second),
                compressor_hz=hz, defrost=df,
                r141_fresh=True, r241_fresh=True)
        self.assertEqual(result["compressor_starts"], 1)
        self.assertEqual(result["defrost_starts"], 1)
        self.assertIsNone(c.path)

        measurements = derive(CircuitSample(
            twi=31, two=34, tao=2, tsat_ps_actual=-2.5,
            tsat_pd_actual=32.6, td=47.1, ps_actual=0.6,
            pd_actual=2.2, compressor_actual_hz=40,
            compressor_target_hz=55),
            r141_fresh=True, r241_fresh=True)
        self.assertEqual(measurements["water_delta_t"], 3.0)
        self.assertEqual(measurements["pressure_delta_mpa"], 1.6)

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
