import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from adaptive.live_runtime import Runtime

class StorageAudit(unittest.TestCase):
    def runtime(self, path):
        r = Runtime.__new__(Runtime)
        r.experiment_path = path
        r.experiment_since = None
        r.experiment_initial = None
        r.experiment_saved = False
        r.experiment_error = None
        r.experiment_counts_saved = [0]*len(r.EXPERIMENT_LEVELS)
        r.experiment_watermark = 0
        r.experiment_metrics = [[] for _ in r.EXPERIMENT_LEVELS]
        r.observer = SimpleNamespace(rows=[])
        r.load_experiment()
        return r

    def test_migration_restart_and_eviction(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/".adaptive-experiment.json"
            since = time.time()-100
            path.write_text(json.dumps({"schema":1,"session":{"since":since,"initial":["eco",False]}}))
            r = self.runtime(path)
            row = {"context":["experiment","eco",False],"start":{"at":since+1}}
            r.observer.rows = [row]
            r.checkpoint_experiment_progress()
            self.assertEqual(r.experiment_counts()[0],1)
            r = self.runtime(path)
            self.assertEqual(r.experiment_counts()[0],1)
            r.observer.rows = [row]
            self.assertEqual(r.experiment_counts()[0],1)
            r.observer.rows = []
            self.assertEqual(r.experiment_counts()[0],1)
            r.observer.rows = [{"context":["experiment","eco",False],"start":{"at":since+i}} for i in range(2,7)]
            r.checkpoint_experiment_progress()
            self.assertEqual(self.runtime(path).experiment_counts()[0],3)

    def test_metrics_survive_eviction_and_finished_restart(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/".adaptive-experiment.json"
            since=time.time()-100
            path.write_text(json.dumps({"schema":1,"session":{"since":since,"initial":["eco",False]}}))
            r=self.runtime(path)
            r.observer.rows=[{"context":["experiment","eco",False],"start":{"at":since+1},
                "stop":{"two":[35],"twi":[30],"fact":[25],"outdoor":2},"run_seconds":600}]
            r.checkpoint_experiment_progress()
            r=self.runtime(path)
            self.assertEqual(r.experiment_comparison()["rows"][0]["run_seconds"],600)
            self.assertEqual(r.experiment_comparison()["rows"][0]["stop_delta"],5)
            r.persist_experiment({"since":since,"initial":["eco",False],"counts":r.experiment_counts(),
                "watermark":r.experiment_watermark,"metrics":r.experiment_metrics,"finished":True})
            r=self.runtime(path)
            self.assertFalse(r.experiment_saved)
            self.assertEqual(r.experiment_comparison()["rows"][0]["retained"],1)

    def test_building_trend(self):
        r=self.runtime(None)
        r.building_rates=[(30,0.01,20)]*30
        self.assertAlmostEqual(r.building_summary()["room_trend_k_h"],1.2)
        r.building_rates=[]
        self.assertIsNone(r.building_summary()["room_trend_k_h"])

    def test_diagnostics_read_only(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/".adaptive-test.json"
            path.write_text("test")
            before = path.stat().st_mtime_ns
            r = self.runtime(Path(d)/".adaptive-experiment.json")
            data = r.storage_diagnostics()
            self.assertEqual(data["state_files"][path.name],4)
            self.assertGreater(data["disk_total_bytes"],0)
            self.assertEqual(path.stat().st_mtime_ns,before)
            self.assertEqual(list(Path(d).iterdir()),[path])


class PassiveInsightTests(unittest.TestCase):
    def sample(self,now,hz=0,defrost=False,**kw):
        return SimpleNamespace(now=now,hz=hz,defrost=defrost,fresh=True,
            dhw=kw.get("dhw",False),error=0,override=False)

    def test_thermal_requires_continuity_and_distinct_states(self):
        from adaptive.regulator import PassiveInsights
        p=PassiveInsights()
        for i in range(361):
            p.observe(self.sample(i*30),True,22-i*30/3600*0.4,2)
        d=p.summary(10800)["thermal"]
        self.assertGreaterEqual(d["idle"]["windows"],3)
        self.assertAlmostEqual(d["idle"]["median_k_h"],-.4,places=2)
        self.assertIsNotNone(d["cooling_proxy_h"])
        self.assertEqual(d["run"]["windows"],0)
        p.observe(self.sample(11000,hz=25),True,21,2)
        self.assertIsNone(p.segment["start"])
        p.observe(self.sample(11030,hz=25),True,None,2)
        self.assertIsNone(p.segment)

    def test_defrost_duration_recovery_and_gap(self):
        from adaptive.regulator import PassiveInsights
        p=PassiveInsights()
        for i in range(0,301,30):
            p.observe(self.sample(i,hz=25,defrost=30<=i<210),True)
        d=p.summary(300)["defrost_24h"]
        self.assertEqual(d["completed"],1)
        self.assertEqual(d["median_seconds"],180)
        self.assertEqual(d["recovery_median_seconds"],0)
        p.observe(self.sample(330,hz=25,defrost=True),True)
        p.observe(self.sample(500,hz=25),True)
        self.assertEqual(p.summary(500)["defrost_24h"]["completed"],1)

    def test_stability_is_bounded_and_reports_coverage(self):
        from adaptive.regulator import PassiveInsights
        p=PassiveInsights()
        for i in range(1000):
            p.resource(i*900,{"VmRSS_bytes":100+i,"threads":3,"open_fds":8,
                                "write_bytes_bytes":i*4096})
        self.assertLessEqual(len(p.resources),673)
        d=p.summary(999*900)
        self.assertTrue(d["stability_24h"]["complete"])
        self.assertEqual(d["stability_24h"]["write_bytes_per_day"],96*4096)
        self.assertEqual(d["stability_24h"]["threads"]["delta"],0)
        self.assertTrue(d["stability_7d"]["complete"])
        self.assertFalse(p.summary(999*900+4000)["stability_24h"]["complete"])

    def test_experiment_weather_spread_uses_all_samples(self):
        r=Runtime.__new__(Runtime)
        r.experiment_since=1
        r.experiment_counts=lambda:[3]*6
        groups=[[[i*3+j+1,600+60*i,25,5,2] for j in range(3)] for i in range(6)]
        r.experiment_samples=lambda:groups
        self.assertTrue(r.experiment_comparison()["comparable"])
        self.assertIn("Najdłuższa",r.experiment_comparison()["observations"][0])
        groups[0][0][4]=8
        self.assertFalse(r.experiment_comparison()["comparable"])
        groups[0][0][4]=None
        self.assertFalse(r.experiment_comparison()["comparable"])


if __name__ == "__main__":
    unittest.main()
