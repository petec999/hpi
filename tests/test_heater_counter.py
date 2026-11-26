import unittest
import tempfile
from pathlib import Path
from adaptive.regulator import HeaterCounter

class HeaterCounterTest(unittest.TestCase):
    def test_edges_gaps_and_persistence(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"heater.json"
            h=HeaterCounter(p)
            a=[0]*16
            h.observe(a,0,0,1000)
            a[3]=256
            h.observe(a,30,30,1030)
            h.observe(a,60,60,1060)
            h.observe(a,60,61,1061)
            self.assertEqual(h.starts,1)
            self.assertEqual(h.seconds,30)
            h.observe(a,200,200,1200)
            self.assertEqual(h.seconds,30)
            self.assertEqual(h.starts,1)
            a[3]=0
            h.observe(a,230,230,1230)
            self.assertEqual(h.events,[[1030,True],[1230,False]])
            h.save_if_due(230)
            b=HeaterCounter(p)
            self.assertEqual((b.starts,b.seconds),(1,30))
            a[3]=256
            b.observe(a,300,300,1300)
            self.assertEqual(b.starts,1)
            self.assertIsNone(b.summary(361)["state"])
