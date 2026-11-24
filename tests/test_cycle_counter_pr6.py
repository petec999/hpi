"""Offline regression tests for the PR6 counter; no heat pump needed."""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from diagnostics.cycle_counter import CycleCounter

BASE = datetime(2026, 11, 24, 10, 0, tzinfo=timezone.utc)


class CycleCounterTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "counts.json"
        self.counter = CycleCounter(self.path)

    def sample(self, seconds, hz=0, df=False, fresh=True):
        return self.counter.observe(BASE + timedelta(seconds=seconds),
            compressor_hz=hz, defrost=df,
            r141_fresh=fresh, r241_fresh=fresh)

    def test_starts_runtime_and_defrost(self):
        self.sample(0)
        self.assertEqual(self.sample(30, hz=42)["compressor_starts"], 1)
        self.assertEqual(self.sample(60, hz=40, df=True)["defrost_starts"], 1)
        result = self.sample(90, hz=40, df=True)
        self.assertEqual(result["compressor_seconds"], 60)
        self.assertEqual(result["defrost_seconds"], 30)
        result = self.sample(120)
        self.assertEqual(result["compressor_completed_cycles"], 1)
        self.assertEqual(result["defrost_completed_cycles"], 1)
        self.assertEqual(result["compressor_last_cycle_seconds"], 60)

    def test_stale_breaks_continuity(self):
        self.sample(0, hz=40)
        self.sample(30, hz=40, fresh=False)
        result = self.sample(60, hz=40)
        self.assertEqual(result["compressor_starts"], 0)
        self.assertEqual(result["compressor_seconds"], 0)

    def test_gap_does_not_create_start(self):
        self.sample(0)
        self.assertEqual(self.sample(400, hz=40)["compressor_starts"], 0)

    def test_restart_preserves_daily_totals(self):
        self.sample(0)
        self.sample(30, hz=40)
        second = CycleCounter(self.path)
        result = second.observe(BASE + timedelta(seconds=60),
            compressor_hz=40, defrost=False,
            r141_fresh=True, r241_fresh=True)
        self.assertEqual(result["compressor_starts"], 1)
        self.assertEqual(result["compressor_seconds"], 0)

    def test_day_boundary(self):
        self.sample(0)
        self.sample(30, hz=40)
        result = self.counter.observe(BASE + timedelta(days=1),
            compressor_hz=40, defrost=False,
            r141_fresh=True, r241_fresh=True)
        self.assertEqual(result["compressor_starts"], 0)

    def test_bad_data_rejected(self):
        self.sample(0)
        for value in (None, float("nan"), float("inf"), -1, True):
            result = self.counter.observe(BASE + timedelta(seconds=30),
                compressor_hz=value, defrost=False,
                r141_fresh=True, r241_fresh=True)
            self.assertEqual(result["compressor_starts"], 0)
        with self.assertRaises(ValueError):
            self.counter.observe(datetime(2026, 11, 24),
                compressor_hz=20, defrost=False,
                r141_fresh=True, r241_fresh=True)


if __name__ == "__main__":
    unittest.main()
