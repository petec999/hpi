import os
import runpy
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import logging
from adaptive.live_runtime import Runtime

ROOT=Path(__file__).resolve().parents[1]

class FakeGPIO:
    values={1:"1",2:"1"}
    @classmethod
    def input(cls,pin):
        return cls.values[pin]

class Decoder:
    GetCHTemp=staticmethod(lambda r:32)
    GetTwiTwo=staticmethod(lambda r:[34,38])
    GetCompInfo=staticmethod(lambda r:[45,45,2,320,30])
    GetMode=staticmethod(lambda r:"turbo")
    Get3way=staticmethod(lambda r:"CH")
    GetDefrost=staticmethod(lambda r:"OFF")
    GetAntifreeze=staticmethod(lambda r:"OFF")
    GetError=staticmethod(lambda r:0)

class RuntimeTest(unittest.TestCase):
    def setUp(self):
        self.writes=[]
        self.g=dict(logging=logging,GPIO=FakeGPIO,PyHaier=Decoder,
                    freqlimitpin=1,heatdemandpin=2,get_temp_zone=lambda v:"normal",
                    statusdict={k:{"value":"off"} for k in ("defrost","antifreeze","service_set_pump","service_set_heater","antifreeze_custom","anti_legionella_active","ch_cooling")},
                    flimit="auto",presetautochange="auto",newframe=[])
        self.g["statusdict"].update(pch={"value":"on"},ch_heating={"value":"on"},hcurve={"value":32},outtemp={"value":1})
        self.g["new_presetchange"]=lambda v:(self.writes.append(("preset",v)),True)
        self.g["flimitchange"]=lambda v:(self.writes.append(("relay",v)),"success")
        self.r=Runtime(self.g)
        self.clock=patch("adaptive.live_runtime.time.monotonic",return_value=1000)
        self.now=self.clock.start()
        self.addCleanup(self.clock.stop)
        self.refresh()
    def refresh(self):
        for k,n in self.r.SIZES.items():
            self.r.note(k,[5]+[0]*(n-1))
    def test_legacy_default(self):
        self.r.tick()
        self.assertEqual(self.r.control,"legacy")
        self.assertFalse(self.writes)
        self.r.legacy("preset","eco","normal")
        self.assertEqual(self.writes,[("preset","eco")])
    def test_actual_readback_and_stale_frames(self):
        s,zone,curve,_=self.r.snapshot()
        self.assertEqual((s.target,s.hz,s.mode,s.relay),(32,45,"turbo",True))
        self.now.return_value=1061
        with self.assertRaises(ValueError):
            self.r.snapshot()
        with self.assertRaises(ValueError):
            self.r.choose("auto","legacy")
    def test_gpio_failure_not_a_valid_off_state(self):
        with patch.object(FakeGPIO,"input",return_value=False):
            with self.assertRaises(ValueError):
                self.r.snapshot()
            with self.assertRaises(ValueError):
                self.r.choose("auto","legacy")
    def test_manual_ownership(self):
        self.r.choose("manual","legacy")
        self.r.legacy("preset","eco","normal")
        self.r.legacy("relay","0","normal")
        self.assertFalse(self.writes)
        self.r.manual("preset","quiet")
        self.assertEqual(self.writes,[("preset","quiet")])
    def test_priority_override(self):
        self.r.choose("manual","legacy")
        self.r.legacy("preset","turbo","frost")
        self.r.priority_write("relay","0")
        self.assertEqual(self.writes,[("preset","turbo"),("relay","0")])
    def test_auto_owns_outputs_independent_of_legacy_settings(self):
        self.g.update(flimit="manual",presetautochange="manual")
        self.r.choose("auto","legacy")
        self.assertEqual(self.r.control,"auto")
        self.assertEqual(self.g["flimit"],"manual")
        self.assertEqual(self.g["presetautochange"],"manual")
        self.r.legacy("relay","0","normal")
        self.r.legacy("preset","quiet","normal")
        self.assertFalse(self.writes)
        for now in range(1000,1901,30):
            self.now.return_value=now
            self.refresh()
            self.r.tick()
            if self.r.pending:
                break
        self.assertEqual(self.writes,[("preset","eco")])
        self.assertEqual(self.r.control,"auto")

    def test_activation_blocker_and_priority_preserved(self):
        self.g["get_temp_zone"]=lambda v:"warm"
        self.assertFalse(self.r.view()["ready"])
        self.assertIn("strefa",self.r.view()["activation_blocker"])
        with self.assertRaisesRegex(ValueError,"strefa"):
            self.r.choose("auto","legacy")
        self.assertEqual(self.r.control,"legacy")
        self.assertFalse(self.writes)

    def test_curve_editor_roundtrip_and_conflict(self):
        import configparser
        c=configparser.ConfigParser()
        c.read_dict({"SETTINGS":{"heatingcurve":"manual","heatingcurve_last":"manual","hcslope":"0.5","hcpshift":"0","hcamp":"1","hcman":",".join(["32"]*14),"flimit":"manual"},"MQTT":{"address":"test"}})
        self.g.update(config=c,loadconfig=lambda:None)
        before=self.r.curve_settings()
        self.assertEqual(len(before["points"]),14)
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"config.ini"
            with path.open("w") as f:c.write(f)
            new=dict(before,points=[33.0]*14)
            self.r.save_curve(new,before,path)
            self.assertEqual(self.r.curve_settings(),new)
            reread=configparser.ConfigParser();reread.read(path)
            self.assertEqual(reread["MQTT"]["address"],"test")
            self.assertEqual(reread["SETTINGS"]["flimit"],"manual")
            with self.assertRaises(ValueError):self.r.save_curve(before,before,path)
            with self.assertRaises(ValueError):self.r.save_curve(dict(new,points=[100]*14),new,path)
            self.assertFalse(self.writes)
            self.assertEqual(self.r.control,"legacy")

    def test_pause_reason_stopped_compressor_and_resume(self):
        self.r.choose("auto","legacy")
        with patch.object(Decoder,"GetCompInfo",return_value=[0,0,2,320,30]):
            self.r.tick()
            self.assertEqual(self.r.status["risk"],"paused")
            self.assertIn("Postój sprężarki",self.r.status["reason_pl"])
            self.assertEqual(self.r.control,"auto")
            self.assertFalse(self.writes)
        self.now.return_value+=30
        self.refresh()
        self.r.tick()
        self.assertIn("Zbieranie pomiarów",self.r.status["reason_pl"])
        self.assertEqual(self.r.control,"auto")

    def test_idle_preparation_limits_then_quiet_and_does_not_learn(self):
        self.r.choose("auto","legacy")
        def relay_write(v):
            self.writes.append(("relay",v))
            FakeGPIO.values[1]=v
            return "limit","success"
        self.g["flimitchange"]=relay_write
        self.g["statusdict"]["ch_heating"]["value"]="off"
        with patch.dict(FakeGPIO.values,{1:"0",2:"0"}):
            with patch.object(Decoder,"GetCompInfo",return_value=[0,0,2,320,30]), patch.object(Decoder,"GetMode",return_value="turbo") as mode:
                self.r.tick()
                self.assertFalse(self.writes)
                self.assertEqual(self.r.status["proposed"],"quiet+FLimit")
                self.now.return_value+=30
                self.refresh()
                self.r.tick()
                self.assertEqual(self.writes,[("relay","1")])
                self.now.return_value+=30
                self.refresh()
                self.r.tick()
                self.assertEqual(self.writes,[("relay","1"),("preset","quiet")])
                mode.return_value="quiet"
                self.now.return_value+=30
                self.refresh()
                self.r.tick()
                self.assertIsNone(self.r.pending)
                self.assertIn("gotowe do startu",self.r.status["reason_pl"])
                self.assertEqual(self.r.learning.summary()["observations"],0)
                self.assertIsNone(self.r.learning.trial)
                self.assertEqual(self.r.control,"auto")
                self.now.return_value+=30
                self.refresh()
                self.r.tick()
                self.assertEqual(len(self.writes),2)

    def test_idle_no_writes_when_off_priority_or_starting(self):
        self.r.choose("auto","legacy")
        with patch.object(Decoder,"GetCompInfo",return_value=[0,0,2,320,30]) as comp:
            self.r.tick()
            self.g["statusdict"]["pch"]["value"]="off"
            self.g["statusdict"]["ch_heating"]["value"]="off"
            self.now.return_value+=30
            self.refresh()
            self.r.tick()
            self.assertFalse(self.writes)
            self.g["statusdict"]["pch"]["value"]="on"
            self.g["get_temp_zone"]=lambda v:"frost"
            self.now.return_value+=30
            self.refresh()
            self.r.tick()
            self.assertFalse(self.writes)
            self.g["get_temp_zone"]=lambda v:"normal"
            comp.return_value=[30,0,2,320,30]
            self.now.return_value+=30
            self.refresh()
            self.r.tick()
            self.assertFalse(self.writes)

    def test_real_idle_co_enabled_but_not_actively_heating(self):
        # Reproduce field telemetry: pch=on, ch_heating=off, demand=1,
        # normal zone, zero requested and actual Hz, turbo+FLimit.
        self.g["statusdict"]["ch_heating"]["value"]="off"
        self.r.choose("auto","legacy")
        with patch.object(Decoder,"GetCompInfo",return_value=[0,0,0,320,25]):
            self.r.tick()
            self.assertEqual(self.r.status["proposed"],"quiet+FLimit")
            self.now.return_value+=30
            self.refresh()
            self.r.tick()
            self.assertEqual(self.writes,[("preset","quiet")])
            self.assertEqual(self.r.control,"auto")
            self.assertIsNone(self.r.learning.trial)

    def test_idle_shadow_never_writes(self):
        self.r.choose("shadow","legacy")
        with patch.object(Decoder,"GetCompInfo",return_value=[0,0,2,320,30]):
            for offset in (0,30,60):
                self.now.return_value=1000+offset
                self.refresh()
                self.r.tick()
            self.assertFalse(self.writes)
            self.assertEqual(self.r.status["proposed"],"quiet+FLimit")

    def test_experiment_writes_only_after_fresh_idle(self):
        with patch.dict(FakeGPIO.values,{1:"1",2:"1"}):
            self.r.choose("experiment","legacy")
            for t in range(1000,1181,30):
                self.now.return_value=t
                self.refresh()
                self.r.tick()
            self.assertFalse(self.writes)
            with patch.object(Decoder,"GetCompInfo",return_value=[0,0,0,320,25]):
                self.g["statusdict"]["ch_heating"]["value"]="off"
                for t in (1210,1240):
                    self.now.return_value=t
                    self.refresh()
                    self.r.tick()
                self.assertFalse(self.writes)
                self.now.return_value=1270
                self.refresh()
                self.r.tick()
                self.assertEqual(self.writes,[("preset","eco")])
                self.assertIsNotNone(self.r.pending)
                self.r.choose("shadow","experiment")
                self.assertEqual(self.r.control,"manual")

    def test_experiment_priority_cancels(self):
        self.r.choose("experiment","legacy")
        self.r.priority_write("preset","quiet")
        self.assertEqual(self.r.control,"manual")
        self.assertEqual(self.writes,[("preset","quiet")])

    def test_pause_reason_does_not_hide_bad_data(self):
        from dataclasses import replace
        s,_,_,_=self.r.snapshot()
        reason="paused: operating state or data invalid"
        self.assertIn("pomiarów",self.r.display_reason(replace(s,hz=0,fresh=False),reason))
        self.assertIn("kończy pracę",self.r.display_reason(replace(s,requested_hz=0),reason))
        self.assertIn("Brak aktywnego",self.r.display_reason(replace(s,heating=False),reason))

    def test_auto_manual_handoff(self):
        self.r.choose("auto","legacy")
        self.r.manual("preset","eco")
        self.assertEqual(self.r.control,"manual")
        self.assertEqual(self.writes,[("preset","eco")])
    def test_shadow_never_actuates(self):
        self.r.choose("shadow","legacy")
        for t in range(1000,1901,30):
            self.now.return_value=t
            self.refresh()
            self.r.tick()
        self.assertEqual(self.r.status["proposed"],"eco+FLimit")
        self.assertFalse(self.writes)
    def test_auto_proposal_readback_pending_and_disarm(self):
        self.r.choose("auto","legacy")
        for t in range(1000,1901,30):
            self.now.return_value=t
            self.refresh()
            self.r.tick()
            if self.r.pending:
                break
        self.assertEqual(self.writes,[("preset","eco")])
        self.assertIsNotNone(self.r.pending)
        self.r.choose("manual","auto")
        self.assertEqual(self.r.control,"manual")
        self.now.return_value+=120
        self.refresh()
        self.r.tick()
        self.assertIsNone(self.r.pending)
        self.assertIsNotNone(self.r.fault)
        self.assertEqual(len(self.writes),1)
    def test_learning_requires_confirmed_auto_transition(self):
        self.r.choose("auto","legacy")
        with patch.object(Decoder,"GetMode",return_value="turbo") as mode, patch.object(Decoder,"GetCompInfo",return_value=[45,45,2,320,30]) as comp:
            for now in range(1000,1901,30):
                self.now.return_value=now
                self.refresh()
                self.r.tick()
                if self.r.pending:
                    break
            self.assertEqual(self.writes,[("preset","eco")])
            self.assertIsNone(self.r.learning.trial)
            mode.return_value="eco"
            comp.return_value=[40,40,2,320,30]
            for now in range(now+30,now+361,30):
                self.now.return_value=now
                self.refresh()
                self.r.tick()
            self.assertEqual(self.r.learning.summary()["observations"],1)
            self.assertEqual(self.r.view()["learning"]["contexts"],1)

    def test_auto_disarm_on_lost_telemetry(self):
        self.r.choose("auto","legacy")
        for t in range(1090,1361,30):
            self.now.return_value=t
            self.r.tick()
        self.assertEqual(self.r.control,"manual")
        self.assertFalse(self.writes)

@unittest.skipUnless(os.environ.get("STABLE_ROOT"),"requires pinned extracted Stable")
class SourceIntegration(unittest.TestCase):
    def test_combined_patch_and_idempotence(self):
        installer=runpy.run_path(str(ROOT/"tools/install-adaptive-preview.py"))
        with tempfile.TemporaryDirectory() as td:
            d=Path(td)
            shutil.copyfile(Path(os.environ["STABLE_ROOT"])/"main.py",d/"main.py")
            (d/"HPi").mkdir()
            shutil.copyfile(ROOT/"tests/fixtures/HPi/GPIO.py",d/"HPi/GPIO.py")
            for path,_,new in installer["plan"](d):
                path.write_bytes(new)
            src=(d/"main.py").read_text()
            self.assertIn("_am.tick()",src)
            self.assertIn('GPIO.setup(modbuspin, GPIO.OUT, initial=GPIO.LOW)',src)
            self.assertIn("STABLE MQTT PUBACK HEALTH",src)
            self.assertIn("HOME-IOT WEB UI V2 BEGIN",src)
            import ast
            html=ast.literal_eval(next(l for l in src.splitlines() if l.startswith("_WV_HTML = ")).split("=",1)[1].strip())
            self.assertNotIn('href="/curvecalc"',html)
            self.assertIn('id="am-owner"',html)
            self.assertIn('activation_blocker',html)
            self.assertIn('id="am-curve-recalc"',html)
            self.assertIn('href="#am-curve-editor"',html)
            self.assertIn('id="am-c-save"',html)
            self.assertIn('v.reason_pl||v.reason',html)
            self.assertIn('id="am-return-temp"',html)
            self.assertIn('id="am-stop-margin"',html)
            self.assertIn('paused:"Oczekiwanie"',html)
            self.assertEqual(html.count('id="am-curve-editor"'),1)
            self.assertTrue(all('id="am-cp-'+str(i)+'"' in html for i in range(14)))
            self.assertIn('g["curvecalc"]()',src)
            self.assertIn('"reason":str(exc)',src)
            for url in ("/","/scheduler","/settings","/parameters","/charts"):
                self.assertIn('href="'+url+'"',html)
            # Migrate the already installed learning UI without duplicating it.
            old=html.replace('<a href="#am-curve-editor">Krzywa grzewcza</a>','<a href="/curvecalc">Krzywa grzewcza</a>')
            line=next(l for l in src.splitlines() if l.startswith("_WV_HTML = "))
            (d/"main.py").write_text(src.replace(line,"_WV_HTML = "+repr(old),1))
            self.assertEqual(installer["plan"](d)[0][2].decode(),src)
            (d/"main.py").write_text(src)

            self.assertEqual(installer["plan"](d),[])
            self.assertIn('learning_path="/opt/haier/.adaptive-learning-twi-v2.json"',src)
            self.assertIn('STABLE MQTT RECONNECT v2',src)
            self.assertIn('HOME-IOT MQTT WATCHDOG v2',src)
            # Simulate the previous embedded module: migration must keep all
            # core patches and leave the installed version idempotent.
            old=src.replace('learning_path="/opt/haier/.adaptive-learning-twi-v2.json"','learning_path=None',1)
            (d/"main.py").write_text(old)
            planned=installer["plan"](d)
            self.assertEqual(len(planned),1)
            self.assertEqual(planned[0][0],d/"main.py")
            self.assertEqual(planned[0][2].decode(),src)

