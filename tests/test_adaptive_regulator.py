import unittest
from dataclasses import replace
from adaptive.regulator import Regulator, Sample, LEVELS, adjacent

def sample(t,level=1,supply=32,ret=29,hz=30,**kw):
    mode,relay=LEVELS[level]
    return replace(Sample(t,32,ret,supply,hz,hz,mode,relay,True,False,True),**kw)

class TestPolicy(unittest.TestCase):
    def series(self,r,level=1,start=0,end=900,**kw):
        return [r.step(sample(t,level,**kw)) for t in range(start,end+1,30)]
    def test_six_combinations_one_output_at_a_time(self):
        self.assertEqual(len(LEVELS),6)
        for i in range(6):
            for direction in ("up","down"):
                j=adjacent(i,direction)
                self.assertLessEqual(sum(a!=b for a,b in zip(LEVELS[i],LEVELS[j])),1)
    def test_stable_supply_normal_return_delta_not_shortfall(self):
        ds=self.series(Regulator(),ret=27,end=840)
        self.assertTrue(all(d.proposed==1 for d in ds))
    def test_persistent_shortfall(self):
        ds=self.series(Regulator(),supply=30.9,end=600)
        self.assertEqual(ds[-1].proposed,2)
        self.assertTrue(all(d.proposed==1 for d in ds[:6]))
    def test_small_integrated_deficit(self):
        ds=self.series(Regulator(),supply=31.6,end=1800)
        self.assertEqual(ds[-1].proposed,2)
        self.assertGreater(ds[-1].deficit_integral,4)
    def test_recovering_shortfall(self):
        r=Regulator()
        ds=[r.step(sample(t,supply=min(32,30+t/120),ret=min(32,29+t/120))) for t in range(0,600,30)]
        self.assertTrue(all(d.proposed==1 for d in ds))
    def test_urgent_release(self):
        ds=self.series(Regulator(),level=5,supply=29,end=180)
        self.assertEqual(ds[-1].proposed,3)
    def test_replay_turbo_limit_real_trace(self):
        r=Regulator()
        twi=[29.1,29.0,29.2,29.1,29.3,29.3,29.3,29.4,29.6,29.7,29.7,29.7,29.9]
        two=[32.2,32.3,32.3,32.3,32.4,32.6,32.6,32.6,32.8,32.8,32.9,33.1,32.8]
        ds=[r.step(sample(i*30,level=5,supply=b,ret=a,hz=45)) for i,(a,b) in enumerate(zip(twi,two))]
        self.assertTrue(all(d.proposed==5 for d in ds))
    def test_return_near_stop_even_when_supply_is_not_primary(self):
        ds=self.series(Regulator(),level=5,supply=38,ret=36.2,end=360)
        self.assertEqual(ds[-1].risk,"cycling_risk")
        self.assertEqual(ds[-1].proposed,4)
        self.assertAlmostEqual(ds[-1].predicted_surplus,4.2)
    def test_rising_return_forecast(self):
        r=Regulator()
        ds=[r.step(sample(t,level=5,supply=36+t/120,ret=32+t/120)) for t in range(0,301,30)]
        self.assertTrue(any(d.risk=="cycling_risk" for d in ds))
        self.assertTrue(any(d.proposed==4 for d in ds))
    def test_supply_surplus_alone_is_not_return_stop_risk(self):
        ds=self.series(Regulator(),level=5,supply=36,ret=29,end=900)
        self.assertTrue(all(d.proposed==5 for d in ds))
        self.assertAlmostEqual(ds[-1].predicted_surplus,-3)
    def test_noisy_deadband(self):
        r=Regulator()
        ds=[r.step(sample(t,supply=32+(.2 if t%60==0 else -.2),hz=25)) for t in range(0,1800,30)]
        self.assertTrue(all(d.proposed==1 for d in ds))
    def test_guard_states(self):
        for guard in ({"fresh":False},{"defrost":True},{"dhw":True},{"error":12},{"heating":False},{"hz":0},{"override":True},{"return_temp":float("nan")}):
            ds=self.series(Regulator(),supply=29,**guard)
            self.assertTrue(all(d.current==d.proposed for d in ds))
    def test_manual_legacy(self):
        for control in ("manual","legacy"):
            r=Regulator()
            for t in range(0,900,30):
                d=r.step(sample(t,supply=29),control)
                self.assertEqual(d.current,d.proposed)
    def test_defrost_and_gap_reset(self):
        r=Regulator()
        self.series(r,supply=30.9)
        r.step(sample(930,defrost=True))
        self.assertEqual(r.step(sample(960,supply=30.9)).proposed,1)
        self.assertEqual(r.step(sample(1100,supply=29)).proposed,1)
    def test_target_reset(self):
        r=Regulator()
        self.series(r,supply=30.9)
        self.assertEqual(r.step(sample(930,target=33,supply=30)).proposed,1)
    def test_reduction_failure_and_cooldown(self):
        r=Regulator()
        # turbo+FLimit -> eco+FLimit; actual change observed after proposal
        ds=self.series(r,level=5,supply=38,ret=34,end=450)
        self.assertEqual(ds[-1].proposed,4)
        ds=self.series(r,level=4,start=480,end=780,supply=29.8)
        self.assertEqual(ds[-1].proposed,5)
        self.assertIn("failed",ds[-1].reason)
        ds=self.series(r,level=5,start=810,end=1500,supply=38,ret=34)
        self.assertEqual(ds[-1].proposed,5)
        self.assertGreater(ds[-1].blocked_seconds,0)
    def test_unobserved_proposal_does_not_change_state(self):
        r=Regulator()
        ds=self.series(r,level=5,supply=38,ret=34,end=600)
        self.assertEqual(ds[-1].proposed,4)
        self.assertTrue(all(d.current==5 for d in ds))
        self.assertIsNone(r.trial)
    def test_restriction(self):
        r=Regulator()
        for t in range(0,900,30):
            d=r.step(sample(t,supply=29),allowed={0,1})
            self.assertEqual(d.proposed,1)
    def test_surplus_at_lowest_envelope_does_not_force_stop_or_raise_power(self):
        ds=self.series(Regulator(),level=0,supply=40,ret=36.2,hz=40,end=900)
        self.assertTrue(all(d.proposed==0 for d in ds))
        self.assertEqual(ds[-1].risk,"cycling_risk_at_minimum")
    def test_deficit_can_release_lowest_envelope(self):
        ds=self.series(Regulator(),level=0,supply=29,hz=40,end=300)
        self.assertEqual(ds[-1].proposed,1)
    def test_native_stop_request_no_proposal(self):
        ds=self.series(Regulator(),level=5,supply=36,ret=34,requested_hz=0,end=900)
        self.assertTrue(all(d.current==d.proposed for d in ds))
        self.assertTrue(all(d.risk=="paused" for d in ds))
    def test_risk_visible_during_settling(self):
        ds=self.series(Regulator(),level=0,supply=40,ret=36.2,end=120)
        self.assertEqual(ds[-1].risk,"cycling_risk_at_minimum")
        self.assertEqual(ds[-1].proposed,0)
    def test_balanced_low_frequency_no_probe(self):
        ds=self.series(Regulator(),hz=24,end=2400)
        self.assertTrue(all(d.proposed==1 for d in ds))

if __name__=="__main__":
    unittest.main()
