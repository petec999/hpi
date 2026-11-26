import tempfile
import unittest
from pathlib import Path
from adaptive.regulator import RegisterWatch

def frames():
    return {k:[0]*n for k,n in RegisterWatch.SIZES.items()}

class RegisterWatchTest(unittest.TestCase):
    def test_reference_edges_and_dhw_samples(self):
        w=RegisterWatch()
        a=frames()
        w.observe(a,(0,)*4,{"tank":48},0,1000)
        a["R241"][3]=4
        w.observe(a,(30,)*4,{"tank":47.9},30,1030)
        self.assertEqual(len(w.events),1)
        a["R101"][0]=2
        a["R141"][3]=256
        a["R241"][3]=12
        w.observe(a,(60,)*4,{"tank":47.8},60,1060)
        self.assertEqual(len(w.events),2)
        e=w.summary(60)["events"][-1]
        self.assertIn("heater_readback",e["flags"])
        self.assertIn({"register":244,"before":4,"after":12,"xor":8,"set_bits":[3],"cleared_bits":[]},e["changes"])
        for t in (90,120,150,180):
            w.observe(a,(t,)*4,{"tank":47.8},t,1000+t)
        self.assertEqual(w.events[-1]["kind"],"dhw_sample")
        self.assertEqual(len(w.events),3)
        self.assertFalse(w.summary(250)["fresh"])

    def test_persistence_and_gap(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"watch.json"
            w=RegisterWatch(p)
            a=frames()
            w.observe(a,(0,)*4,{},0,1000)
            w.save_if_due(0)
            a["R141"][3]=256
            w.observe(a,(200,)*4,{},200,1200)
            self.assertEqual(len(w.events),1)
            w.observe(a,(230,)*4,{},230,1230)
            a["R141"][3]=0
            w.observe(a,(260,)*4,{},260,1260)
            self.assertEqual(len(w.events),2)
            w.save_if_due(1799)
            self.assertEqual(len(RegisterWatch(p).events),1)
            w.save_if_due(1800)
            self.assertEqual(RegisterWatch(p).events,w.events)

    def test_cap(self):
        w=RegisterWatch()
        a=frames()
        for i in range(300):
            a["R141"][3]=256*(i%2)
            w.observe(a,(i*30,)*4,{},i*30,1000+i*30)
        self.assertEqual(len(w.events),256)
