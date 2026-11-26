import json
import unittest
from adaptive.shadow import Availability, Observation, decode, describe
from adaptive.regulator import Regulator

class Shadow(unittest.TestCase):
    def record(self,**updates):
        d=dict(hcurve=32,twitwo=[29,31],compinfo=[30,30,4,320,25],
               mode="quiet",flimiton="0",flrelay=0,pch="on",heatdemand="1",
               ch_heating="on",threeway="CH",error=0,defrost="off",
               service_set_pump="off",service_set_heater="off",antifreeze="off",
               antifreeze_custom="off",anti_legionella_active="off",ch_cooling="off",
               tempzone="normal",antionoff="0")
        d.update(updates)
        return {"__REALTIME_TIMESTAMP":"100000000","MESSAGE":"status_snapshot: "+json.dumps(d)}

    def test_snapshot(self):
        s,data=decode(self.record(),1,True,100)
        self.assertEqual((s.return_temp,s.supply_temp,s.hz,s.requested_hz),(29,31,30,30))
        self.assertTrue(s.heating)
        d=Regulator().step(s)
        self.assertEqual(describe(s,data,d,{})["control"],"shadow")

    def test_invalid(self):
        for updates in (dict(flimiton="1"),dict(error="N.A."),dict(mode="x"),dict(threeway="x"),dict(twitwo=[29]),dict(service_set_pump="N.A.")):
            with self.subTest(updates=updates):
                with self.assertRaises((ValueError,IndexError)):
                    decode(self.record(**updates),1,True,100)
        with self.assertRaises(ValueError):
            decode(self.record(),1,True,146)
        with self.assertRaises(ValueError):
            decode(self.record(),1,True,99)

    def test_overrides(self):
        for key in ("service_set_pump","service_set_heater","antifreeze","antifreeze_custom","anti_legionella_active","ch_cooling"):
            s,_=decode(self.record(**{key:"on"}),1,True,100)
            self.assertTrue(s.override)

    def test_availability_needs_live_heartbeat(self):
        a=Availability()
        for k in a.states:
            a.update(k,"online",True,1)
        self.assertFalse(a.status(2)[0])
        a.update("connected","online",False,2)
        self.assertTrue(a.status(2)[0])
        self.assertFalse(a.status(93)[0])
        old=a.status(3)[1]
        a.update("r141_fresh","offline",False,3)
        a.update("r141_fresh","online",False,4)
        self.assertGreater(a.status(4)[1],old)
        a.reset()
        self.assertFalse(a.status(5)[0])

    def test_stale_or_idle_no_proposals(self):
        for fresh in (False,True):
            r=Regulator()
            for t in range(0,900,30):
                s,_=decode(self.record(compinfo=[0,0,0,320,25] if fresh else [30,30,4,320,25]),t,fresh,100)
                d=r.step(s)
                self.assertEqual(d.current,d.proposed)

    def test_all_six_combinations_observed(self):
        for mode in ("quiet","eco","turbo"):
            for relay in ("0","1"):
                obs=Observation()
                r=Regulator()
                for t in range(0,151,30):
                    s,data=decode(self.record(mode=mode,flimiton=relay,flrelay=relay,
                                              twitwo=[29+t/300,32.2]),t,True,100)
                    metrics=obs.update(s)
                    d=r.step(s)
                self.assertEqual(metrics["observed_seconds"],150)
                self.assertEqual(metrics["supply_deficit"],-0.2)
                self.assertLess(metrics["return_trend_k_min"],0)
                if relay=="1" and mode!="quiet":
                    self.assertIsNone(d.proposed)
                stale,_=decode(self.record(),180,False,100)
                self.assertEqual(obs.update(stale),{})
                self.assertEqual(len(obs.history),0)
