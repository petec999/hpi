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

    def test_extended_metrics_and_old_data(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"obs.json"
            o=HysteresisObserver(p)
            for t in range(0,901,30):
                o.observe(sample(t,300<=t<750),"experiment",True,1700000000+t,outdoor=2)
            q=o.summary()
            self.assertEqual(q["mean"]["stop"]["offset"],.25)
            self.assertEqual(q["extended"]["stop_fact"],35)
            self.assertEqual(q["extended"]["stop_fset"],35)
            self.assertEqual(q["extended"]["stop_outdoor"],2)
            self.assertEqual(q["extended"]["stop_water_delta"],3)
            self.assertEqual(q["extended"]["run_seconds"],450)
            self.assertEqual(q["extended"]["above_seconds"]["twi"]["0"],420)
            self.assertEqual(q["extended"]["above_seconds"]["twi"]["2"],0)
            o.save_if_due(900)
            n=HysteresisObserver(p)
            self.assertEqual(len(n.rows),1)
            data=json.loads(p.read_text())
            data["schema"]=1
            for row in data["cycles"]:
                row["context"][0]="legacy"
                row.pop("above_seconds")
                row.pop("run_seconds")
                for e in ("start","stop"):
                    for k in ("outdoor","fact","fset"):
                        row[e].pop(k)
            p.write_text(json.dumps(data))
            n=HysteresisObserver(p)
            self.assertEqual(len(n.rows),1)
            n.context=("legacy","eco",False,32)
            self.assertEqual(n.summary()["mean"]["stop"]["offset"],.25)
            self.assertEqual(n.summary()["extended"]["cycles"],0)
            self.assertIsNone(n.summary()["extended"]["stop_fact"])

    def test_rejection_reason_once_and_context_change(self):
        o=HysteresisObserver()
        self.feed(o,lambda t,s: replace(s,target=33) if t>=450 else s)
        diag=o.summary()["diagnostics"]
        self.assertEqual(diag["reasons"],{"target_changed":1})
        self.assertEqual(diag["last_rejection"]["detail"],"32 → 33 °C")
        self.assertEqual(diag["rejected"],1)

    def test_repeated_invalid_polls_reject_once(self):
        o=HysteresisObserver()
        for t in range(0,901,30):
            o.observe(sample(t,300<=t<750),"legacy",t<600,1700000000+t,reason="no_demand")
        self.assertEqual(o.summary()["diagnostics"]["reasons"],{"no_demand":1})
        self.assertEqual(o.summary()["diagnostics"]["blocker"],"no_demand")

    def test_short_idle_and_run_are_diagnosed(self):
        o=HysteresisObserver()
        for t in range(0,901,30):
            o.observe(sample(t,60<=t<180 or 510<=t<600),"legacy",True,1700000000+t)
        self.assertEqual(o.summary()["diagnostics"]["reasons"],{"short_idle":1,"short_run":1})
        self.assertEqual(len(o.rows),0)
