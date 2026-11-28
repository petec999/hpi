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


class ExperimentGuardTests(unittest.TestCase):
    def sample(self,t,**kw):
        from adaptive.regulator import Sample
        data=dict(now=t,target=35,return_temp=30,supply_temp=32,hz=25,
                  requested_hz=25,mode="quiet",relay=True,heating=True,
                  defrost=False,fresh=True)
        data.update(kw)
        return Sample(**data)

    def test_long_run_with_comfort_is_not_a_failure(self):
        from adaptive.regulator import ExperimentGuard
        g=ExperimentGuard()
        for t in range(0,7201,30):
            hz=25+(t//30)%4
            self.assertIsNone(g.observe(self.sample(t,supply_temp=35,hz=hz,requested_hz=hz),21,True))
        self.assertEqual(g.heating_state,"modulating")
        self.assertEqual(g.water_seconds,0)

    def test_flat_water_deficit_on_frequency_plateau_is_capacity_shortfall(self):
        from adaptive.regulator import ExperimentGuard
        g=ExperimentGuard()
        for t in range(0,1800,30):
            self.assertIsNone(g.observe(self.sample(t,hz=40,requested_hz=40),21,True))
        self.assertEqual(g.observe(self.sample(1800,hz=40,requested_hz=40),21,True),"water_shortfall")
        self.assertEqual(g.heating_state,"capacity_shortfall")

    def test_plateau_below_limit_not_capacity_shortfall(self):
        from adaptive.regulator import ExperimentGuard
        g=ExperimentGuard()
        for t in range(0,3601,30):
            self.assertIsNone(g.observe(self.sample(t,hz=25,requested_hz=25),21,True))
        self.assertEqual(g.capacity_state,"modulating_shortfall")
        self.assertEqual(g.water_seconds,3600)

    def test_capacity_learning_persistence_and_probe_guard(self):
        from adaptive.regulator import CapacityLearning
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/".adaptive-capacity-v1.json"
            model=CapacityLearning(path)
            wall=time.time()-14400
            for t in range(0,12601,30):
                model.observe(self.sample(t,hz=40,requested_hz=40),1,True,wall+t)
            self.assertTrue(model.avoid_probe(self.sample(12600),1,("quiet",True)))
            self.assertFalse(model.avoid_probe(self.sample(12600),1,("eco",True)))
            self.assertFalse(model.avoid_probe(self.sample(12600),5,("quiet",True)))
            model.save_if_due(12600)
            self.assertIsNone(model.error)
            loaded=CapacityLearning(path)
            self.assertIsNone(loaded.error)
            self.assertTrue(loaded.avoid_probe(self.sample(12600),1,("quiet",True)))
            before=loaded.summary()["hours"]
            loaded.observe(self.sample(13000,hz=40,requested_hz=40),1,True,wall+13000)
            loaded.observe(self.sample(13030,hz=40,requested_hz=40),1,True,wall+13030)
            self.assertEqual(loaded.summary()["hours"],before)

    def test_capacity_learning_excludes_defrost_and_gap(self):
        from adaptive.regulator import CapacityLearning
        model=CapacityLearning()
        for t in range(0,1201,30):
            model.observe(self.sample(t,hz=40,requested_hz=40),1,True,1000+t)
        self.assertAlmostEqual(model.summary()["hours"],300/3600)
        model.observe(self.sample(1230,defrost=True),1,True,2230)
        model.observe(self.sample(1260,hz=40,requested_hz=40),1,True,2260)
        model.observe(self.sample(1500,hz=40,requested_hz=40),1,True,2500)
        self.assertAlmostEqual(model.summary()["hours"],300/3600)

    def test_rising_twi_or_two_does_not_confirm_capacity_shortfall(self):
        from adaptive.regulator import ExperimentGuard
        for sensor in ("return_temp","supply_temp"):
            with self.subTest(sensor=sensor):
                g=ExperimentGuard()
                for t in range(0,1801,30):
                    self.assertIsNone(g.observe(self.sample(t,hz=40,requested_hz=40,**{sensor:29+t/600}),21,True))
                self.assertEqual(g.water_seconds,1800)
                self.assertEqual(g.heating_state,"water_below_target")

    def test_duplicate_frames_and_gaps_do_not_build_running_stability(self):
        from adaptive.regulator import ExperimentGuard
        g=ExperimentGuard()
        for t in range(0,1801,30):
            g.observe(self.sample(t,supply_temp=35),21,True,frame_at=0)
        self.assertEqual(g.running_seconds,0)
        for t in range(1830,2731,30):
            g.observe(self.sample(t,supply_temp=35),21,True)
        self.assertTrue(g.running_stable(self.sample(2730)))
        ramp=self.sample(2760,hz=40,requested_hz=40)
        g.observe(ramp,21,True)
        self.assertFalse(g.running_stable(ramp))
        after_gap=self.sample(3000)
        g.observe(after_gap,21,True)
        self.assertEqual(g.running_seconds,0)

    def test_room_drop_and_recovery(self):
        from adaptive.regulator import ExperimentGuard
        g=ExperimentGuard()
        self.assertIsNone(g.observe(self.sample(0),21,True))
        for t in range(30,630,30):
            self.assertIsNone(g.observe(self.sample(t),20.5,True))
        self.assertEqual(g.observe(self.sample(630),20.5,True),"room_shortfall")
        g.reset()
        for t in range(660,1560,30):
            self.assertIsNone(g.observe(self.sample(t,mode="turbo",relay=False,supply_temp=35),20.9,True,True))
        self.assertEqual(g.observe(self.sample(1560,mode="turbo",relay=False,supply_temp=35),20.9,True,True),"recovered")

    def test_water_only_when_room_unavailable(self):
        from adaptive.regulator import ExperimentGuard
        g=ExperimentGuard()
        for t in range(0,1800,30):
            self.assertIsNone(g.observe(self.sample(t,return_temp=34),None,True))
        self.assertEqual(g.observe(self.sample(1800,return_temp=34),None,True),"water_shortfall")
        # A fresh comfort reading cancels the water-only fallback.
        self.assertIsNone(g.observe(self.sample(1830,return_temp=34),21,True))
        self.assertIsNone(g.observe(self.sample(1860,defrost=True),None,True))
        self.assertEqual(g.water_seconds,0)
        self.assertIsNone(g.observe(self.sample(2000),None,True))

    def test_weather_retry_and_validation(self):
        from adaptive.regulator import ExperimentGuard
        g=ExperimentGuard()
        self.assertFalse(g.can_retry({"outdoor":-2},-1))
        self.assertTrue(g.can_retry({"outdoor":-2},0))
        self.assertFalse(g.can_retry({"outdoor":None},0))
        self.assertFalse(g.can_retry({"outdoor":-2},None))
        with self.assertRaises(ValueError):
            ExperimentGuard(dict(g.DEFAULT,water_minutes=0))

    def test_continuous_trial_separate_from_hysteresis(self):
        from adaptive.regulator import ContinuousTrial
        g=ContinuousTrial()
        for t in range(0,11700,30):
            self.assertIsNone(g.observe(self.sample(t),21,1,21,19,True,1000+t))
        trial=g.observe(self.sample(11700),21,1,21,19,True,12700)
        self.assertEqual(trial["seconds"],10800)
        self.assertEqual(trial["start"],1900)
        self.assertEqual(trial["stop"],12700)
        self.assertEqual(g.seconds,0)
        for t in range(12000,12960,30):
            g.observe(self.sample(t),21,1,21,19,True,1000+t)
        self.assertGreater(g.seconds,0)
        g.observe(self.sample(12960,defrost=True),21,1,21,19,True,13960)
        self.assertGreater(g.seconds,0)
        self.assertIsNotNone(g.window)
        g.observe(self.sample(13000,dhw=True),21,1,21,19,True,14000)
        self.assertEqual(g.seconds,0)
        self.assertIsNone(g.window)

    def test_winter_blocks_include_defrost_and_idle_and_reject_idle_only(self):
        from adaptive.regulator import ContinuousTrial
        g=ContinuousTrial(duration=1800)
        trial=None
        for t in range(0,2701,30):
            idle=1200<=t<1380
            d=1500<=t<1680
            trial=g.observe(self.sample(t,defrost=d,heating=not idle,hz=0 if idle else 25,
                          requested_hz=0 if idle else 25),21,1 if t<1800 else 2,21,19,True,1000+t)
        self.assertIsNotNone(trial)
        self.assertEqual(trial["seconds"],1800)
        self.assertEqual(trial["defrosts"],1)
        self.assertEqual(trial["starts"],1)
        self.assertGreater(trial["idle_seconds"],0)
        self.assertGreater(trial["defrost_seconds"],0)
        self.assertEqual(sum(trial[k] for k in ("run_seconds","idle_seconds","defrost_seconds","transition_seconds")),1800)
        g=ContinuousTrial(duration=1800)
        for t in range(0,2701,30):
            self.assertIsNone(g.observe(self.sample(t,hz=0,requested_hz=0,heating=False),21,1,21,19,True,1000+t))
        self.assertEqual(g.reason,"insufficient_heating")

    def test_winter_partial_windows_survive_restart_and_exclude_gaps(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/".adaptive-experiment.json"
            since=time.time()-20000
            path.write_text(json.dumps({"schema":1,"session":{"since":since,"initial":["eco",False],"counts":[1,0,0,0,0,0]}}))
            r=StorageAudit().runtime(path)
            def window(i):
                start=since+100+i*3000
                return dict(start=start,stop=start+1800,seconds=1800,
                    outdoor_min=0,outdoor_max=1,target_min=35,target_max=36,room_min=20.8,room_max=21,
                    run_seconds=1440,idle_seconds=120,defrost_seconds=180,transition_seconds=60,
                    starts=1,short_cycles=0,defrosts=1,energy=None)
            r.experiment_windows[0]=[window(i) for i in range(3)]
            r.save_guard_checkpoint()
            r=StorageAudit().runtime(path)
            self.assertEqual(len(r.experiment_windows[0]),3)
            self.assertEqual(r.experiment_counts()[0],1)
            r.experiment_windows[0].extend(window(i) for i in range(3,6))
            result=r.combine_trial_windows(r.experiment_windows[0])
            self.assertEqual(result["seconds"],10800)
            self.assertEqual(result["blocks"],6)
            self.assertEqual(result["defrosts"],6)
            self.assertGreater(result["stop"]-result["start"],result["seconds"])
            r.experiment_continuous[0]=result
            r.experiment_windows[0]=[]
            r.save_guard_checkpoint()
            r=StorageAudit().runtime(path)
            self.assertEqual(r.experiment_continuous[0]["seconds"],10800)
            self.assertEqual(r.experiment_continuous[0]["starts"],6)
            self.assertFalse(r.experiment_windows[0])

    def test_continuous_trial_checkpoint(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/".adaptive-experiment.json"
            since=time.time()-12000
            path.write_text(json.dumps({"schema":1,"session":{"since":since,"initial":["eco",False],"counts":[1,0,0,0,0,0]}}))
            r=StorageAudit().runtime(path)
            r.experiment_continuous[0]={"start":since+900,"stop":since+11700,"seconds":10800,
                "outdoor_min":0,"outdoor_max":1,"target_min":35,"target_max":35.5,"room_min":21,"room_max":21.1,"energy":None}
            r.save_guard_checkpoint()
            resumed=StorageAudit().runtime(path)
            self.assertEqual(resumed.experiment_counts()[0],1)
            self.assertEqual(resumed.experiment_comparison()["rows"][0]["quality"],"continuous")
            self.assertEqual(resumed.experiment_continuous[0]["seconds"],10800)

    def test_guard_checkpoint_preserves_cycles_and_deferrals(self):
        from adaptive.regulator import ExperimentGuard
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/".adaptive-experiment.json"
            since=time.time()-1000
            path.write_text(json.dumps({"schema":1,"session":{"since":since,"initial":["eco",False],"counts":[1,0,0,0,0,0]}}))
            r=StorageAudit().runtime(path)
            r.experiment_guard.reference=21
            r.experiment_deferred[1]={"at":since+500,"outdoor":-2,"room":20.5,"target":35,"two":32,"reason":"room_shortfall"}
            r.experiment_recovering=True
            r.save_guard_checkpoint()
            resumed=StorageAudit().runtime(path)
            self.assertEqual(resumed.experiment_counts()[0],1)
            self.assertEqual(resumed.experiment_deferred[1]["outdoor"],-2)
            self.assertEqual(resumed.experiment_guard.reference,21)
            self.assertTrue(resumed.experiment_recovering)

class NotificationTests(unittest.TestCase):
    def test_notification_transitions(self):
        import runpy
        path=Path(__file__).resolve().parents[1]/"tools/haierpi-notify.py"
        runpy.run_path(str(path))["selftest"]()


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


class BackupTests(unittest.TestCase):
    def test_backup_manifest_rotation_and_path_validation(self):
        import runpy
        import tarfile
        import io
        from unittest.mock import patch
        b=runpy.run_path(str(Path(__file__).resolve().parents[1]/"tools/haierpi-backup.py"))
        g=b["create"].__globals__
        payload={"opt/config.ini":b"[HA]\nkey=value\n","opt/haier/main.py":b"pass\n",
                 "opt/haier/HPi/GPIO.py":b"pass\n","opt/haier/.adaptive-experiment-v1.json":b"{}"}
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"backups"
            with patch.dict(g,{"STORE":root,"sources":lambda:payload}):
                for _ in range(8):
                    name=b["create"]()
                    self.assertEqual(b["validate"](root/name),payload)
                self.assertEqual(len(b["archives"]()),7)
                self.assertEqual(root.stat().st_mode&0o777,0o700)
                with self.assertRaises(ValueError):
                    b["archive_path"]("../outside")
                bad=root/"bad.tar.gz"
                with tarfile.open(bad,"w:gz") as t:
                    m=tarfile.TarInfo("../outside");m.size=1
                    t.addfile(m,io.BytesIO(b"x"))
                with self.assertRaises(ValueError):
                    b["validate"](bad)
                with tarfile.open(bad,"w:gz") as t:
                    m=tarfile.TarInfo("opt/config.ini");m.type=tarfile.SYMTYPE;m.linkname="/etc/passwd"
                    t.addfile(m)
                with self.assertRaises(ValueError):
                    b["validate"](bad)
                with tarfile.open(bad,"w:gz") as t:
                    m=tarfile.TarInfo("manifest.json");m.size=2
                    t.addfile(m,io.BytesIO(b"{}"))
                with self.assertRaises(ValueError):
                    b["validate"](bad)

    def test_backup_web_patch_and_access_controls(self):
        import runpy
        b=runpy.run_path(str(Path(__file__).resolve().parents[1]/"tools/patch-backup.py"))
        source='_WV_HTML = "<nav></nav>"\n# HOME-IOT WEB UI V2 END\n'
        result=b["patch"](source)
        self.assertEqual(b["patch"](result),result)
        self.assertIn('href="/v2/backup"',result)
        self.assertEqual(result.count("@login_required"),3)
        self.assertIn("X-HaierPi-CSRF",result)
        self.assertIn("systemd-run",result)
        compile(result,"main.py","exec")

class WinterDashboardTests(unittest.TestCase):
    def test_existing_dashboard_const_collision_and_idempotence(self):
        import runpy
        import shutil
        import subprocess
        patch=runpy.run_path(str(Path(__file__).resolve().parents[1]/"tools/patch-adaptive-preview.py"))
        upgrade=patch["winter_status_ui"]
        html='''<p id="am-continuous-status"></p>
<script>
function amPaint(v){
 const ex=v.experiment;
 const continuous=[];
 const reasons={target_changed:"change"};
 $("am-continuous-status").textContent=ex?"old":"";
}
</script>'''
        fixed=upgrade(html)
        self.assertIn("const amWinterReasons=",fixed)
        self.assertEqual(fixed.count("const reasons="),1)
        broken=fixed.replace("amWinterReasons","reasons")
        self.assertEqual(upgrade(broken),fixed)
        self.assertEqual(upgrade(fixed),fixed)
        node=shutil.which("node")
        if node:
            js=fixed.split("<script>",1)[1].split("</script>",1)[0]
            subprocess.run([node,"--check","-"],input=js,text=True,check=True)

if __name__ == "__main__":
    unittest.main()
