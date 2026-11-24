"""Read-only PR8 SQLite historian regression suite."""
import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from diagnostics.history_store import HistoryStore
from diagnostics.mqtt_history import HistoryCollector, parse_numeric

UTC = timezone.utc
DAY = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)


class HistoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "history.sqlite"
        self.store = HistoryStore(self.path)
        self.addCleanup(self.store.close)

    def test_persistence_restart_and_csv(self):
        self.store.sample("HaierPi_Twi", 30.2, "°C", DAY)
        self.store.event("state_change", "HaierPi_Defrost", "off", "on", DAY)
        other = HistoryStore(self.path)
        self.assertEqual(other.summary()["sample_count"], 1)
        self.assertEqual(other.summary()["event_count"], 1)
        other.export_csv(self.root / "samples.csv", "samples")
        other.export_csv(self.root / "events.csv", "events")
        with (self.root / "samples.csv").open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(rows[0]["unique_id"], "HaierPi_Twi")
        self.assertEqual(float(rows[0]["value"]), 30.2)
        other.close()

    def test_retention(self):
        old = DAY - timedelta(days=110)
        self.store.sample("HaierPi_Two", 32, timestamp=old)
        self.store.sample("HaierPi_Two", 34, timestamp=DAY)
        self.store.event("state_change", "HaierPi_Defrost", "off", "on", old)
        result = self.store.prune(90, now=DAY)
        self.assertEqual(result, (1, 1))
        self.assertEqual(self.store.summary()["sample_count"], 1)
        self.assertEqual(self.store.summary()["event_count"], 0)

    def test_collector_samples_and_event_transitions(self):
        history = HistoryCollector(self.store, minimum_interval=60)
        self.assertEqual(history.discover({
            "uniq_id": "HaierPi_Twi", "stat_t": "climate/haier/details/twitwo",
            "val_tpl": "{{ value_json[0] | float }}", "unit_of_measurement": "°C"}),
            "climate/haier/details/twitwo")
        history.discover({
            "unique_id": "HaierPi_Defrost",
            "state_topic": "climate/haier/details/defrost/state"})
        history.receive("climate/haier/details/twitwo", "[30,35]", timestamp=DAY, monotonic=100)
        history.receive("climate/haier/details/twitwo", "[31,35]", timestamp=DAY + timedelta(seconds=20), monotonic=120)
        history.receive("climate/haier/details/twitwo", "[32,35]", timestamp=DAY + timedelta(seconds=61), monotonic=161)
        self.assertEqual(self.store.summary()["sample_count"], 2)
        history.receive("climate/haier/details/defrost/state", "off", timestamp=DAY, monotonic=100)
        history.receive("climate/haier/details/defrost/state", "on", timestamp=DAY + timedelta(seconds=61), monotonic=161)
        history.receive("climate/haier/details/defrost/state", "on", timestamp=DAY + timedelta(seconds=62), monotonic=162)
        self.assertEqual(self.store.summary()["event_count"], 1)

    def test_retained_and_reconnect_do_not_make_fake_events(self):
        history = HistoryCollector(self.store)
        history.discover({"uniq_id": "HaierPi_Defrost",
                          "stat_t": "climate/haier/details/defrost/state"})
        topic = "climate/haier/details/defrost/state"
        history.receive(topic, "off", retained=True)
        history.receive(topic, "on")
        history.reset_session()
        history.receive(topic, "off")
        self.assertEqual(self.store.summary()["event_count"], 0)

    def test_unsafe_topics_and_invalid_values_rejected(self):
        history = HistoryCollector(self.store)
        self.assertIsNone(history.discover({
            "uniq_id": "HaierPi_Twi", "stat_t": "other/device/secret"}))
        history.discover({"uniq_id": "HaierPi_Twi",
                          "stat_t": "climate/haier/details/twitwo",
                          "val_tpl": "{{ value_json[0] | float }}"})
        for bad in ("NaN", "[null]", "garbage"):
            history.receive("climate/haier/details/twitwo", bad,
                            timestamp=DAY, monotonic=100)
        self.assertEqual(self.store.summary()["sample_count"], 0)
        with self.assertRaises(ValueError):
            parse_numeric("21", "{{ 2 + 2 }}")

    def test_query_export_allowlist(self):
        with self.assertRaises(ValueError):
            self.store.export_csv(self.root / "evil.csv", "sqlite_master")
        with self.assertRaises(ValueError):
            self.store.sample("MY_PASSWORD", 123, timestamp=DAY)


if __name__ == "__main__":
    unittest.main()
