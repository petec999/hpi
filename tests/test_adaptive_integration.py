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
    GetTwiTwo=staticmethod(lambda r:[29,32.9])
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
        self.g["statusdict"].update(ch_heating={"value":"on"},hcurve={"value":32},outtemp={"value":1})
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
            self.assertEqual(installer["plan"](d),[])
            self.assertIn('learning_path="/opt/haier/.adaptive-learning.json"',src)
            self.assertIn('STABLE MQTT RECONNECT v2',src)
            self.assertIn('HOME-IOT MQTT WATCHDOG v2',src)
            # Simulate the previous embedded module: migration must keep all
            # core patches and leave the installed version idempotent.
            old=src.replace('learning_path="/opt/haier/.adaptive-learning.json"','learning_path=None',1)
            (d/"main.py").write_text(old)
            planned=installer["plan"](d)
            self.assertEqual(len(planned),1)
            self.assertEqual(planned[0][0],d/"main.py")
            self.assertEqual(planned[0][2].decode(),src)

