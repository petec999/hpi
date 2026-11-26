import tempfile
import unittest
from pathlib import Path
from dataclasses import replace
from adaptive.regulator import Learning, Sample, LEVELS, Settings, adjacent

def sample(t,level=5,supply=38,hz=45,**kw):
    mode,relay=LEVELS[level]
    return replace(Sample(t,32,34 if supply>=34 else 29,supply,hz,hz,mode,relay,True,False,True),**kw)

class LearningTest(unittest.TestCase):
    def trial(self,l,supply=38,hz=40,outdoor=1):
        l.start(sample(0),sample(30,4,supply,hz),outdoor)
        for t in range(60,331,30):
            l.observe(sample(t,4,supply,hz),outdoor)

    def test_learn_only_observed_reductions_and_context(self):
        l=Learning()
        for i in range(3):
            self.trial(l)
        self.assertEqual(l.summary()["observations"],3)
        self.assertLess(l.settings(sample(0),1).down_confirm,90)
        self.assertEqual(l.settings(sample(0),-6),Settings())
        self.assertEqual(l.settings(sample(0,level=4),1),Settings())
        self.assertEqual(l.settings(sample(0,target=36),1),Settings())

    def test_supply_risk_learns_before_next_reduction_even_with_cold_return(self):
        l=Learning()
        for i in range(3):
            l.start(sample(0),sample(30,4,supply=36.8,return_temp=29),1)
            for t in range(60,211,30):
                l.observe(sample(t,4,supply=36.8,return_temp=29),1)
        self.assertEqual(l.summary()["observations"],3)
        self.assertLess(l.settings(sample(0),1).down_confirm,90)

    def test_failed_reductions_adjust_conservatively(self):
        l=Learning()
        for i in range(3):
            self.trial(l,supply=30)
        cfg=l.settings(sample(0),1)
        self.assertGreater(cfg.down_confirm,90)
        self.assertEqual(cfg.urgent_confirm,Settings().urgent_confirm)
        self.assertEqual(cfg.up_confirm,Settings().up_confirm)

    def test_no_learning_from_interruptions(self):
        for kwargs in ({"defrost":True},{"dhw":True},{"fresh":False},{"target":34},{"requested_hz":0}):
            l=Learning()
            l.start(sample(0),sample(30,4),1)
            l.observe(sample(60,4,**kwargs),1)
            self.assertIsNone(l.trial)
            self.assertFalse(l.rows)
        l=Learning()
        l.start(sample(0),sample(30,4),1)
        l.observe(sample(100,4),1)
        self.assertIsNone(l.trial)

    def test_persistence_bounded_and_reload(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"learning.json"
            l=Learning(p)
            self.trial(l)
            l.save_if_due(1000)
            first=p.read_bytes()
            self.trial(l)
            l.save_if_due(1001)
            self.assertEqual(first,p.read_bytes())
            l.save_if_due(2799)
            self.assertEqual(first,p.read_bytes())
            l.save_if_due(2800)
            self.assertEqual(Learning(p).summary()["observations"],2)
            saved=p.read_bytes()
            l.save_if_due(4600)
            self.assertEqual(saved,p.read_bytes())
            p.write_text("corrupt")
            self.assertEqual(Learning(p).summary()["observations"],0)

    def test_extended_context_capacity_roundtrip_and_eviction(self):
        # Use real valid context keys and distinct last-update times.
        from unittest.mock import patch
        keys=[f"{a}:{b}:{c}:{adjacent(c,'down')}"
              for a in range(-8,10) for b in range(3,22)
              for c in range(len(LEVELS)) if adjacent(c,"down")!=c]
        self.assertGreater(len(keys),1024)
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"learning.json"
            l=Learning(p)
            self.assertEqual(l.MAX_CONTEXTS,1024)
            self.assertEqual(l.SAVE_INTERVAL,1800)
            for i,key in enumerate(keys[:1024]):
                with patch("adaptive.regulator.time.time",return_value=10000+i):
                    l.record(key,0,1.25,0.5,0.1)
            l.save_if_due(1000)
            self.assertGreater(p.stat().st_size,65536)
            self.assertLessEqual(p.stat().st_size,l.MAX_FILE_BYTES)
            restored=Learning(p)
            self.assertEqual(restored.rows,l.rows)
            with patch("adaptive.regulator.time.time",return_value=20000):
                restored.record(keys[0],1,2.0,0.5,0.1)
            with patch("adaptive.regulator.time.time",return_value=20001):
                restored.record(keys[1024],0,1.0,0.5,0.1)
            self.assertEqual(len(restored.rows),1024)
            self.assertIn(keys[0],restored.rows)
            self.assertNotIn(keys[1],restored.rows)
            self.assertIn(keys[1024],restored.rows)
            restored.save_if_due(restored.last_save+1800)
            self.assertEqual(Learning(p).rows,restored.rows)

    def test_old_schema_does_not_tune_return_policy(self):
        import json
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"old.json"
            p.write_text(json.dumps({"schema":1,"contexts":{}}))
            l=Learning(p)
            self.assertEqual(l.settings(sample(0),1),Settings())
            self.assertFalse(l.rows)
    def test_no_learning_on_wrong_transition(self):
        l=Learning()
        l.start(sample(0,4),sample(30,5),1)
        self.assertIsNone(l.trial)
