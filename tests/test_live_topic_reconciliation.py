"""Regression for real HaierPi: live /haierunit/ MQTT from 2026-11-24."""
import tempfile
import unittest
from pathlib import Path

from diagnostics.source_topics import live_state_topic
from diagnostics.mqtt_cycle_bridge import MQTTInput
from diagnostics.mqtt_circuit_bridge import TelemetryState, SOURCE_IDS


BASE = "climate/haier"


class LiveTopicReconciliationTests(unittest.TestCase):
    def test_live_discovery_topic_is_not_rewritten(self):
        self.assertEqual(live_state_topic(
            "HaierPi_Compfact", BASE + "/haierunit/compressor/info/state", BASE),
            BASE + "/haierunit/compressor/info/state")
        self.assertEqual(live_state_topic(
            "HaierPi_Twi", BASE + "/details/twitwo/state", BASE),
            BASE + "/details/twitwo/state")
        self.assertEqual(live_state_topic(
            "unknown_id", BASE + "/haierunit/secret/state", BASE),
            BASE + "/haierunit/secret/state")

    def test_pr6_real_haierpi_mqtt_topics(self):
        s = MQTTInput()
        s.discover({"unique_id": "HaierPi_Compfact",
                    "state_topic": BASE + "/haierunit/compressor/info/state",
                    "value_template": "{{ value_json[1] | float }}"})
        s.discover({"unique_id": "HaierPi_Defrost",
                    "state_topic": BASE + "/haierunit/statuses/defrost/state"})
        for key in ("connected", "r141", "r241"):
            s.availability(key, "online")
        s.update(BASE + "/haierunit/compressor/info/state", "[0, 0, 0.0, 320, 25.0]", now=100)
        s.update(BASE + "/haierunit/statuses/defrost/state", "off", now=100)
        self.assertEqual(s.current(now=101), (0.0, False))

    def test_pr7_real_haierpi_discovery_uses_live_haierunit(self):
        s = TelemetryState()
        s.configure({"unique_id": "HaierPi_Twi",
                     "state_topic": BASE + "/haierunit/temperatures/twitwo/state",
                     "value_template": "{{ value_json[0] | float }}"})
        self.assertEqual(s.mapping["twi"][0], BASE + "/haierunit/temperatures/twitwo/state")
        s.update_state(BASE + "/haierunit/temperatures/twitwo/state", "[50.6,51.0]", now=100)
        self.assertEqual(s.values["twi"][0], 50.6)

    def test_pr7_all_ten_sensors_using_actual_haierpi_trace(self):
        s = TelemetryState()
        rows = [
            ("HaierPi_Tao", "temperatures/tao", "", "12.8"),
            ("HaierPi_Twi", "temperatures/twitwo", "{{ value_json[0] | float }}", "[50.6,51.0]"),
            ("HaierPi_Two", "temperatures/twitwo", "{{ value_json[1] | float }}", "[50.6,51.0]"),
            ("HaierPi_Compfact", "compressor/info", "{{ value_json[1] | float }}", "[0,0,0.0,320,25.0]"),
            ("HaierPi_Compfset", "compressor/info", "{{ value_json[0] | float }}", "[0,0,0.0,320,25.0]"),
            ("HaierPi_Td", "temperatures/tdts", "{{ value_json[0] | float }}", "[57.0,16.0]"),
            ("HaierPi_Pd_act", "pressures/pdps", "{{ value_json[1] | float }}", "[23.8,10.6,8.6,10.8]"),
            ("HaierPi_Ps_act", "pressures/pdps", "{{ value_json[3] | float }}", "[23.8,10.6,8.6,10.8]"),
            ("HaierPi_TSatPd_act", "temperatures/tsatpd", "{{ value_json[1] | float }}", "[40.0,11.7]"),
            ("HaierPi_TSatPs_act", "temperatures/tsatps", "{{ value_json[1] | float }}", "[5.6,11.9]"),
        ]
        for uid, suffix, template, payload in rows:
            self.assertTrue(s.configure({
                "unique_id": uid,
                "state_topic": BASE + "/haierunit/" + suffix + "/state",
                "value_template": template,
                "unit_of_measurement": "bar" if uid in ("HaierPi_Pd_act", "HaierPi_Ps_act") else ""}))
        for key in ("r141", "r241", "bridge"):
            s.set_availability(key, "online")
        for uid, suffix, template, payload in rows:
            s.update_state(BASE + "/haierunit/" + suffix + "/state", payload, now=100)
        result = s.calculate(now=101)
        self.assertIsNotNone(result)
        self.assertEqual(result["water_delta_t"], 0.4)
        self.assertEqual(result["pressure_delta_mpa"], -0.02)
        self.assertEqual(result["compressor_frequency_error_hz"], 0.0)



if __name__ == "__main__":
    unittest.main()
