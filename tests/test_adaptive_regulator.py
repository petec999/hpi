import unittest
from dataclasses import replace
from adaptive.regulator import Regulator, Sample

def sample(t,delta=3,level=1,**kw):
    from adaptive.regulator import LEVELS
    mode,relay=LEVELS[level]
    s=Sample(t,32,32-delta,32.3,30,30,mode,relay,True,False,True)
    return replace(s,**kw)

class TestPolicy(unittest.TestCase):
    def run_series(self,r,delta,level=1,start=0,end=900,**kw):
        return [r.step(sample(t,delta,level,**kw)) for t in range(start,end+1,30)]
    def test_sustained_shortfall(self):
        ds=self.run_series(Regulator(),3.5)
        self.assertEqual(ds[-1].proposed,2)
        self.assertTrue(all(d.proposed==1 for d in ds[:14]))
    def test_reduce_slowly(self):
        ds=self.run_series(Regulator(),1.0,level=1)
        self.assertEqual(ds[-1].proposed,0)
        self.assertTrue(all(d.proposed==1 for d in ds[:20]))
    def test_hysteresis(self):
        r=Regulator()
        ds=[r.step(sample(t,2.8+(.2 if t%60==0 else -.2))) for t in range(0,1200,30)]
        self.assertTrue(all(d.proposed==1 for d in ds))
    def test_recovering_delta(self):
        r=Regulator()
        ds=[r.step(sample(t,5-t/300)) for t in range(0,601,30)]
        self.assertTrue(all(d.proposed==1 for d in ds))
    def test_guards(self):
        for guard in ({"fresh":False},{"defrost":True},{"dhw":True},{"error":12},{"heating":False},{"hz":0},{"override":True},{"return_temp":float("nan")}):
            ds=self.run_series(Regulator(),7,**guard)
            self.assertTrue(all(d.current==d.proposed for d in ds))
    def test_manual_legacy_no_proposals(self):
        for control in ("manual","legacy"):
            r=Regulator()
            for t in range(0,1200,30):
                d=r.step(sample(t,9),control)
                self.assertEqual(d.current,d.proposed)
    def test_urgent_one_step(self):
        ds=self.run_series(Regulator(),7,level=0,end=120)
        self.assertEqual(ds[-1].proposed,1)
    def test_resume_after_defrost(self):
        r=Regulator()
        self.run_series(r,3.5)
        r.step(sample(930,3.5,defrost=True))
        ds=self.run_series(r,3.5,start=960,end=1200)
        self.assertTrue(all(d.proposed==1 for d in ds))
    def test_target_change_resets(self):
        r=Regulator()
        self.run_series(r,3.5)
        d=r.step(sample(930,3.5,target=33))
        self.assertEqual(d.current,d.proposed)
    def test_stale_gap_resets(self):
        r=Regulator()
        self.run_series(r,3.5)
        d=r.step(sample(1100,3.5))
        self.assertEqual(d.current,d.proposed)
    def test_ceiling(self):
        r=Regulator()
        for t in range(0,900,30):
            d=r.step(sample(t,7),ceiling=1)
            self.assertEqual(d.proposed,1)
    def test_observed_change_wait(self):
        r=Regulator()
        self.run_series(r,3.5)
        ds=self.run_series(r,4.7,level=2,start=930,end=1170)
        self.assertTrue(all(d.proposed==2 for d in ds))

if __name__=="__main__":
    unittest.main()
