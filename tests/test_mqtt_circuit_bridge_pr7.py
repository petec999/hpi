"""Offline tests of the MQTT bridge without a broker or heat pump."""
import unittest
from diagnostics.mqtt_circuit_bridge import TelemetryState, SOURCE_IDS, decode_value

TOPICS = {
    "twi": ("x/twitwo", "{{ value_json[0] | float }}"),
    "two": ("x/twitwo", "{{ value_json[1] | float }}"),
    "tao": ("x/tao", ""),
    "tsat_ps_actual": ("x/tsatps", "{{ value_json[1] | float }}"),
    "tsat_pd_actual": ("x/tsatpd", "{{ value_json[1] | float }}"),
    "td": ("x/tdts", "{{ value_json[0] | float }}"),
    "ps_actual": ("x/ps", "{{ value_json[1] | float }}"),
    "pd_actual": ("x/pd", "{{ value_json[1] | float }}"),
    "compressor_actual_hz": ("x/compinfo", "{{ value_json[1] | float }}"),
    "compressor_target_hz": ("x/compinfo", "{{ value_json[0] | float }}"),
}
MESSAGES = {
    "x/twitwo": "[31, 34]",
    "x/tao": "2",
    "x/tsatps": "[-2, -2.5]",
    "x/tsatpd": "[33, 32.6]",
    "x/tdts": "[47.1, 10]",
    "x/ps": "[0.6, 0.6]",
    "x/pd": "[2.2, 2.2]",
    "x/compinfo": "[55, 40, 5.0, 220, 35]",
}


def ready():
    s = TelemetryState()
    for field, uid in SOURCE_IDS.items():
        topic, template = TOPICS[field]
        assert s.configure({"uniq_id": uid, "stat_t": topic,
                            "val_tpl": template})
    for key in ("r141", "r241", "bridge"):
        s.set_availability(key, "online")
    return s


class MQTTBridgeTests(unittest.TestCase):
    def test_decode_templates_and_reject_arbitrary_jinja(self):
        self.assertEqual(decode_value("[5, 9]", "{{ value_json[1] | float }}"), 9)
        self.assertEqual(decode_value('{"temp": 8}', "{{ value_json.temp }}"), 8)
        self.assertEqual(decode_value("21.5", ""), 21.5)
        with self.assertRaises(ValueError):
            decode_value("[1,2]", "{{ 2 + 2 }}")

    def test_mqtt_discovery_and_derivation(self):
        s = ready()
        for topic, msg in MESSAGES.items():
            s.update_state(topic, msg, now=100)
        values = s.calculate(now=110)
        self.assertEqual(values["water_delta_t"], 3)
        self.assertEqual(values["saturation_lift"], 35.1)
        self.assertEqual(values["ambient_evaporating_approach"], 4.5)
        self.assertEqual(values["discharge_condensing_gap"], 14.5)
        self.assertEqual(values["pressure_delta_mpa"], 1.6)
        self.assertEqual(values["compressor_frequency_error_hz"], 15)

    def test_retained_telemetry_is_not_assumed_current(self):
        s = ready()
        for topic, msg in MESSAGES.items():
            s.update_state(topic, msg, retained=True, now=100)
        self.assertIsNone(s.calculate(now=101))

    def test_missing_stale_or_offline_measurement(self):
        s = ready()
        for topic, msg in MESSAGES.items():
            s.update_state(topic, msg, now=100)
        self.assertIsNone(s.calculate(now=251))
        s.set_availability("r241", "offline")
        self.assertIsNone(s.calculate(now=105))
        self.assertEqual(s.values, {})

    def test_invalid_payload_invalidates_measurement(self):
        s = ready()
        for topic, msg in MESSAGES.items():
            s.update_state(topic, msg, now=100)
        s.update_state("x/tao", "not a number", now=101)
        self.assertIsNone(s.calculate(now=102))


if __name__ == "__main__":
    unittest.main()
