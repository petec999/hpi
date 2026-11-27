import ast
import configparser
import io
import os
import tempfile
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

    def test_config_atomic_and_noop(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"config.ini"
            cfg=configparser.ConfigParser()
            cfg["test"]={"a":"1"}
            env={"threading":threading,"os":os,"io":io,"tempfile":tempfile,"config":cfg}
            exec(PATCH["CONFIG_HELPER"].replace("/opt/config.ini",str(path)),env)
            save=env["_hpi_save_config"]
            save()
            st=path.stat()
            save()
            self.assertEqual(st.st_ino,path.stat().st_ino)
            cfg["test"]["a"]="2"
            save()
            self.assertIn("a = 2",path.read_text())
            self.assertEqual(path.stat().st_mode & 0o777,0o600)
            self.assertEqual(list(Path(d).iterdir()),[path])

    def test_helper_compiles(self):
        ast.parse(PATCH["HELPER"])

if __name__=="__main__":
    unittest.main()
