"""Regression: the live controller uses /haierunit/statuses/defrost/state."""
import unittest
from diagnostics.source_topics import live_state_topic


class DefrostTopicTests(unittest.TestCase):
    def test_defrost_discovery_topic_is_not_rewritten(self):
        base = "climate/haier"
        actual = base + "/haierunit/statuses/defrost/state"
        self.assertEqual(live_state_topic("HaierPi_Defrost", actual, base), actual)

    def test_known_legacy_telemetry_is_redirected(self):
        base = "climate/haier"
        old = base + "/haierunit/temperatures/twitwo/state"
        self.assertEqual(live_state_topic("HaierPi_Twi", old, base),
                         base + "/details/twitwo/state")


if __name__ == "__main__":
    unittest.main()
