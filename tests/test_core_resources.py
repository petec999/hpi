import ast
import logging
import runpy
import threading
import time
import unittest
from pathlib import Path

PATCH = runpy.run_path(str(Path(__file__).resolve().parents[1] / "tools/patch-core-resources.py"))

class ResourceGuards(unittest.TestCase):
    def test_worker_single_flight_and_shutdown(self):
        env={"threading":threading,"logging":logging,"event":threading.Event()}
        exec(PATCH["HELPER"],env)
        start=env["_hpi_start_once"]
        release=threading.Event()
        try:
            self.assertTrue(start("test",lambda:release.wait(5)))
            for _ in range(1000):
                self.assertFalse(start("test",lambda:None))
            self.assertEqual(len(env["_hpi_active_workers"]),1)
        finally:
            release.set()
        deadline=time.monotonic()+2
        while env["_hpi_active_workers"] and time.monotonic()<deadline:
            time.sleep(.01)
        self.assertFalse(env["_hpi_active_workers"])
        env["event"].set()
        self.assertFalse(start("other",lambda:None))

    def test_worker_exception_releases_slot(self):
        env={"threading":threading,"logging":logging,"event":threading.Event()}
        exec(PATCH["HELPER"],env)
        def fail():
            raise ValueError("test")
        with self.assertLogs(level="ERROR"):
            self.assertTrue(env["_hpi_start_once"]("test",fail))
            deadline=time.monotonic()+2
            while env["_hpi_active_workers"] and time.monotonic()<deadline:
                time.sleep(.01)
        self.assertFalse(env["_hpi_active_workers"])

    def test_reject_unknown_and_partial_patch(self):
        with self.assertRaises(ValueError):
            PATCH["patch"]("pass")
        with self.assertRaises(ValueError):
            PATCH["patch"](PATCH["MARK"]+"\n")

    def test_helper_compiles(self):
        ast.parse(PATCH["HELPER"])

if __name__=="__main__":
    unittest.main()
