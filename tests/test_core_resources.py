import ast
import json
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

class HostAuditTests(unittest.TestCase):
    def setUp(self):
        self.audit=runpy.run_path(str(Path(__file__).resolve().parents[1]/"tools/host-resource-audit.py"))

    def test_inventory_does_not_follow_symlinks(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/"charts.pkl").write_bytes(b"123")
            (root/".before-upgrade").mkdir()
            (root/".before-upgrade"/"file").write_bytes(b"12")
            (root/".adaptive-test").symlink_to(root/"charts.pkl")
            (root/".before-upgrade"/"loop").symlink_to(root, target_is_directory=True)
            result=self.audit["inventory"](root)
            self.assertEqual(result["charts"]["bytes"],3)
            self.assertEqual(result["adaptive_state"]["files"],0)
            self.assertEqual(result["upgrade_rollback"]["bytes"],2)

    def test_process_deltas_and_restart(self):
        a={"at":1,"start_ticks":100,"cpu_ticks":100,"rss_bytes":1024,"threads":2,"fds":5,"write_bytes":4096}
        b=dict(a,at=11,cpu_ticks=150,rss_bytes=2048,write_bytes=8192)
        out=self.audit["difference"](a,b,100)
        self.assertEqual(out["cpu_pct_one_core"],5)
        self.assertEqual(out["write_bytes_delta"],4096)
        self.assertEqual(out["rss_bytes_delta"],1024)
        with self.assertRaises(ValueError):
            self.audit["difference"](a,dict(b,start_ticks=101),100)

    def test_register_evidence_counts_association_not_decoding(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"watch.json"
            old=[0]*16
            new=old.copy()
            new[3]=0x0200
            new[14]=0x0010
            events=[{"before":{"R141":old},"after":{"R141":new},"flags":["heater_readback"]},
                    {"before":{"R141":new},"after":{"R141":old},"flags":[]}]
            path.write_text(json.dumps({"schema":1,"events":events}))
            result=self.audit["register_evidence"](path)
            self.assertEqual(result["valid_pairs"],2)
            self.assertEqual(len(result["candidates"]),2)
            for row in result["candidates"]:
                self.assertEqual((row["rising"],row["falling"],row["with_known_edge"]),(1,1,1))
                self.assertEqual(row["known_edges"],{"heater_readback":1})
            path.write_text("invalid")
            self.assertFalse(self.audit["register_evidence"](path)["available"])

    def test_current_process_readonly(self):
        result=self.audit["snapshot"](os.getpid())
        self.assertGreater(result["rss_bytes"],0)
        self.assertGreaterEqual(result["threads"],1)

if __name__=="__main__":
    unittest.main()
