import tempfile
import unittest
from pathlib import Path
from adaptive.regulator import NativeThresholds, Sample, Regulator, LEVELS

def sample(t,active=False,twi=30,two=30,mode="quiet",relay=True,actual=None):
    hz=30 if active else 0
    return Sample(t,32,twi,two,hz if actual is None else actual,hz,mode,relay,True,False,True)

class ThresholdTest(unittest.TestCase):
    def edges(self,m):
        # START on Quiet+FLimit; change mode during run; STOP on Eco.
        for t in range(0,181,30):
            m.observe(sample(t),True,100000+t,"auto")
        for t in (210,240,270):
            m.observe(sample(t,True),True,100000+t,"auto")
        for t in range(300,481,30):
            m.observe(sample(t,True,33,36.4,"eco",False),True,100000+t,"auto")
        for t in (510,540,570):
            m.observe(sample(t,False,33,36.4,"eco",False),True,100000+t,"auto")
    def test_independent_edges_and_config(self):
        m=NativeThresholds()
        self.edges(m)
        self.assertEqual(len(m.rows["start:0:10"]),1)
        self.assertEqual(len(m.rows["stop:2:10"]),1)
        self.assertEqual(m.model(sample(0))["start"]["source"],"default")
        self.assertEqual(m.model(sample(0,mode="eco",relay=False))["stop"]["n"],1)
    def test_confidence_fallback_and_persistence(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"thresholds.json"
            m=NativeThresholds(p)
            m.rows["stop:2:10"]=[[100+i,1,4.4] for i in range(8)]
            m.rows["start:0:10"]=[[100+i,-2.4,-2.2] for i in range(8)]
            m.dirty=True
            m.save_if_due(1000)
            m=NativeThresholds(p)
            self.assertEqual(m.model(sample(0))["start_target"],29.7)
            g=next(g for g in m.summary()["groups"] if g["edge"]=="start")
            self.assertEqual(len(g["samples"]),8)
            self.assertEqual(g["samples"][0],{"at":100,"twi_offset":-2.4,"two_offset":-2.2})
            g["samples"][0]["two_offset"]=0
            self.assertEqual(m.summary()["groups"][0]["samples"][0]["two_offset"],-2.2)
            self.assertEqual(m.model(sample(0,mode="eco",relay=False))["stop_target"],36.4)
            self.assertEqual(m.model(sample(0))["stop"]["source"],"default")
            m.rows["stop:2:10"]=[[100+i,1,3.8 if i<4 else 5.4] for i in range(8)]
            self.assertEqual(m.model(sample(0,mode="eco",relay=False))["stop"]["source"],"default")
    def test_no_edge_on_priority_or_mode_change(self):
        m=NativeThresholds()
        for t in range(0,181,30):
            m.observe(sample(t),True,100000+t,"auto")
        m.observe(sample(210,True,mode="eco"),True,100210,"auto")
        m.observe(sample(240,True,mode="eco"),False,100240,"auto")
        m.observe(sample(270,True,mode="eco"),True,100270,"auto")
        self.assertFalse(m.rows)
    def test_learned_stop_used_by_regulator(self):
        r=Regulator()
        for t in range(0,361,30):
            d=r.step(sample(t,True,29,35.6,"eco",False),stop_offset=4.4)
        self.assertEqual(d.risk,"cycling_risk")
        self.assertNotEqual(d.current,d.proposed)
        r=Regulator()
        for t in range(0,361,30):
            d=r.step(sample(t,True,29,35.6,"eco",False))
        self.assertEqual(d.risk,"balanced")
    def test_idle_forecast(self):
        m=NativeThresholds()
        for t in range(0,181,30):
            s=sample(t,twi=31-t/300,two=31-t/300)
            m.observe(s,True,100000+t,"auto")
        self.assertAlmostEqual(m.model(s)["start_eta_min"],2.0)
        self.assertIsNone(m.model(sample(181,twi=30.4,two=30.4,mode="eco"))["start_eta_min"])
        self.assertIsNone(m.model(sample(250,twi=30.4,two=30.4))["start_eta_min"])

if __name__=="__main__":
    unittest.main()
