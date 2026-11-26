import tempfile
import unittest
from pathlib import Path
from dataclasses import replace
from adaptive.regulator import HysteresisObserver, Sample

def sample(t, active=False, **kw):
    s=Sample(t,32,34 if active else 29,37 if active else 29,35 if active else 0,35 if active else 0,"eco",False,active,False,True)
    return replace(s,**kw)

class ObserverTests(unittest.TestCase):
    def feed(self,o,change=None,control="legacy",base=0):
        for t in range(0,901,30):
            s=sample(base+t,300<=t<750)
            if change:
                s=change(t,s)
            o.observe(s,control,True,1700000000+base+t)

    def test_completed_cycle_and_persistence(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"obs.json"
            o=HysteresisObserver(p)
            self.feed(o)
            self.assertEqual(o.summary()["cycles"],1)
            self.assertEqual(o.rows[0]["start"]["at"],1700000300)
            self.assertEqual(o.rows[0]["stop"]["at"],1700000750)
            self.assertEqual(o.rows[0]["stop"]["twi"],[2,-3])
            o.save_if_due(900)
            n=HysteresisObserver(p)
            self.assertEqual(len(n.rows),1)
            self.assertEqual(n.since,1700000000)
            self.assertIsNone(n.start)

    def test_changed_target_and_defrost_discard(self):
        for change in (lambda t,s: replace(s,target=33) if t>=450 else s,
                       lambda t,s: replace(s,defrost=True) if t==600 else s):
            o=HysteresisObserver()
            self.feed(o,change)
            self.assertEqual(len(o.rows),0)

    def test_contexts_not_combined(self):
        o=HysteresisObserver()
        self.feed(o)
        self.feed(o,control="manual",base=1200)
        self.assertEqual(o.summary()["total"],2)
        self.assertEqual(o.summary()["cycles"],1)
        self.assertFalse(o.summary()["enough_samples"])

    def test_startup_running_is_not_a_cycle(self):
        o=HysteresisObserver()
        for t in range(0,901,30):
            o.observe(sample(t,t<600),"legacy",True,1700000000+t)
        self.assertEqual(len(o.rows),0)

    def test_missing_demand_discards_cycle(self):
        o=HysteresisObserver()
        for t in range(0,901,30):
            o.observe(sample(t,300<=t<750),"legacy",t!=600,1700000000+t)
        self.assertEqual(len(o.rows),0)
