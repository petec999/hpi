import unittest
from adaptive.live_runtime import Runtime
from adaptive.regulator import Sample

class HeaterControlTest(unittest.TestCase):
    def test_frame_mask(self):
        self.assertEqual(Runtime.heater_frame([0xdd05,1,2,0xddf1,0xdd5a,6],True),[0x100d,1,2,1,0x5a,6])
        self.assertEqual(Runtime.heater_frame([0xdd0d,1,2,0xddf1,0xdd5a,6],True)[0],0x100d)
        self.assertEqual(Runtime.heater_frame([0xdd0d,1,2,0xddf1,0xdd5a,6],False)[0],0x1005)

    def test_default_and_priority(self):
        r=Runtime({})
        self.assertEqual(r.heater_mode,"off")
        s=Sample(0,32,28,29,45,45,"eco",False,True,False,True)
        f={"R101":(0,[0x85]+[0]*5),"R141":(0,[0,0,0,512]+[0]*12)}
        self.assertTrue(r.heater_priority(s,f))
        self.assertFalse(r.heater_mark(True))
        with self.assertRaises(ValueError):
            r.heater_request("bad")
