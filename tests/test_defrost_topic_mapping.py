"""Regression: use the actual HaierPi MQTT Discovery topics seen live."""
import unittest
from diagnostics.source_topics import live_state_topic


class DiscoveryTopicTests(unittest.TestCase):
    def test_defrost_stays_on_original_status_topic(self):
        base = "climate/haier"
        actual = base + "/haierunit/statuses/defrost/state"
        self.assertEqual(live_state_topic("HaierPi_Defrost", actual, base), actual)

    def test_live_haierunit_telemetry_is_not_redirected(self):
        base = "climate/haier"
        samples = {
            "HaierPi_Twi": "temperatures/twitwo",
            "HaierPi_Pd_act": "pressures/pdps",
            "HaierPi_Compfact": "compressor/info",
            "HaierPi_TSatPs_act": "temperatures/tsatps",
        }
        for uid, suffix in samples.items():
            with self.subTest(uid=uid):
                actual = base + "/haierunit/" + suffix + "/state"
                self.assertEqual(live_state_topic(uid, actual, base), actual)

    def test_unknown_source_topic_is_not_affected(self):
        self.assertEqual(live_state_topic("custom", "other/state", "climate/haier"), "other/state")


if __name__ == "__main__":
    unittest.main()
