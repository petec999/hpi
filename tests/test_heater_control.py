import unittest
from unittest.mock import patch
from pathlib import Path
import tempfile
from adaptive.live_runtime import Runtime
from adaptive.regulator import Sample

class HeaterControlTest(unittest.TestCase):
    def test_frame_mask(self):
        self.assertEqual(Runtime.heater_frame([0xdd05,1,2,0xddf1,0xdd5a,6],True),[0x100d,1,2,1,0x5a,6])
        self.assertEqual(Runtime.heater_frame([0xdd0d,1,2,0xddf1,0xdd5a,6],True)[0],0x100d)
        self.assertEqual(Runtime.heater_frame([0xdd0d,1,2,0xddf1,0xdd5a,6],False)[0],0x1005)

    def test_default_and_priority(self):
        r=Runtime({})
        self.assertEqual(r.heater_mode,"auto")
        s=Sample(0,32,28,29,45,45,"eco",False,True,False,True)
        f={"R101":(0,[0x85]+[0]*5),"R141":(0,[0,0,0,512]+[0]*12)}
        self.assertTrue(r.heater_priority(s,f))
        self.assertFalse(r.heater_mark(True))
        with self.assertRaises(ValueError):
            r.heater_request("bad")


    def test_manual_no_time_limit_and_auto_release(self):
        with tempfile.TemporaryDirectory() as td:
            a=[5,0,0,0,0,0]
            b=[0,0,0,0x0200]+[0]*12
            g={"R101":a,"newframe":[],"_hp_ready_for_setters":lambda:True,
               "statusdict":{k:{"value":v} for k,v in
                             (("pdhw","off"),("pump","on"),("pch","on"))}}
            writes=[]
            g["set_newframe"]=lambda reg,frame:writes.append(frame) or True
            r=Runtime(g,Path(td)/"learning.json")
            s=Sample(0,32,28,29,45,45,"eco",False,True,False,True)
            f={"R101":(100,a),"R141":(100,b)}
            with patch.object(r,"heater_snapshot",return_value=(s,f)),patch("adaptive.live_runtime.time.monotonic",return_value=100):
                r.heater_tick(100)
                self.assertEqual(writes,[])
                r.heater_request("on")
                r.heater_tick(100)
                self.assertEqual(len(writes),1)
                self.assertTrue(r.heater_owned)
                b[3]|=256
                f["R141"]=(130,b)
                r.heater_tick(130)
                f["R141"]=(4000,b)
                r.heater_tick(4000)
                self.assertEqual(r.heater_mode,"on")
                self.assertEqual(len(writes),1)
                r.heater_request("auto")
                r.heater_tick(4030)
                self.assertEqual(len(writes),2)
                self.assertEqual(writes[-1][0]&8,0)
                b[3]&=~256
                f["R141"]=(4060,b)
                r.heater_tick(4060)
                self.assertFalse(r.heater_owned)
                self.assertEqual(r.heater_mode,"auto")
                b[3]|=256
                f["R141"]=(4090,b)
                r.heater_tick(4090)
                r.heater_request("off")
                r.heater_tick(4120)
                self.assertEqual(len(writes),2)
