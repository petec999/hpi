import tempfile
import unittest
from pathlib import Path
from dataclasses import replace
from adaptive.regulator import AdaptiveReport, Sample, Learning

def sample(t,active,mode="eco",relay=False,actual=None):
    hz=30 if active else 0
    return Sample(t,32,30,34,hz if actual is None else actual,hz,mode,relay,True,False,True)

class ReportTest(unittest.TestCase):
    def test_cycle_spans_modulation_and_weather_band(self):
        r=AdaptiveReport()
        for t,active,mode in [(0,False,"eco"),(30,True,"eco"),(60,True,"quiet"),(90,True,"turbo"),(120,False,"turbo")]:
            r.observe(sample(t,active,mode),"auto",True,86400+t,4 if t<90 else 5)
        rows=r.snapshot()["groups"]
        self.assertEqual(sum(b["starts"] for b in rows),1)
        self.assertEqual(sum(b["completed"] for b in rows),1)
        self.assertEqual(sum(b["run_s"] for b in rows),90)
        self.assertEqual(sum(b["coverage_s"] for b in rows),120)
        self.assertEqual(sum(b["running_s"] for b in rows),90)
        self.assertEqual(sum(sum(b["levels_s"]) for b in rows),90)

    def test_gap_and_priority_do_not_create_completed_cycle(self):
        r=AdaptiveReport()
        for t,active,ok in [(0,False,True),(30,True,True),(60,True,False),(90,False,True),(120,True,True),(250,False,True)]:
            r.observe(sample(t,active),"auto",ok,86400+t,1)
        self.assertEqual(sum(b["starts"] for b in r.buckets.values()),2)
        self.assertEqual(sum(b["completed"] for b in r.buckets.values()),0)

    def test_persistence_restart_and_learning_counts(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"report.json"
            r=AdaptiveReport(p)
            r.observe(sample(0,False),"legacy",True,86400,1)
            r.observe(sample(30,True),"legacy",True,86430,1)
            l=Learning()
            l.on_record=r.learned
            l.record("0:10:5:4",1,1,1,0)
            r.event("issued","auto","test")
            r.save_if_due(1000)
            restored=AdaptiveReport(p)
            self.assertEqual(restored.buckets,r.buckets)
            self.assertEqual(restored.scores["1"],1)
            self.assertEqual(restored.events,r.events)
            self.assertIsNone(restored.run)
            restored.observe(sample(60,False),"legacy",True,86460,1)
            self.assertEqual(sum(b["completed"] for b in restored.buckets.values()),0)
            r.event("confirmed","auto","test")
            original=p.read_bytes()
            r.save_if_due(2799)
            self.assertEqual(p.read_bytes(),original)
            r.save_if_due(2800)
            self.assertEqual(AdaptiveReport(p).events,r.events)

    def test_continuous_run_spans_modulation_and_target_bands(self):
        r=AdaptiveReport()
        for t in range(0,7231,30):
            s=sample(t,True,"quiet" if t<3600 else "eco")
            s=replace(s,target=32 if t<3600 else 34)
            r.observe(s,"auto",True,86400+t,1)
        data=r.snapshot()
        self.assertEqual(data["current_streak"]["seconds"],7230)
        self.assertEqual(max(b["max_continuous_s"] for b in data["groups"]),7230)
        self.assertEqual(sum(b["beyond_hour_s"] for b in data["groups"]),3630)
        r.observe(sample(7260,False),"auto",True,93660,1)
        self.assertIsNone(r.snapshot()["current_streak"])
        self.assertEqual(max(b["max_continuous_s"] for b in r.buckets.values()),7230)
        r.observe(sample(7290,True),"auto",True,93690,1)
        r.observe(sample(7400,True),"auto",True,93800,1)
        self.assertEqual(r.snapshot()["current_streak"]["seconds"],0)

    def test_old_report_migrates_and_record_survives_restart(self):
        import json
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"report.json"
            r=AdaptiveReport(p)
            for t in (0,30,60):
                r.observe(sample(t,True),"auto",True,86400+t,1)
            r.save_if_due(1000)
            self.assertEqual(max(b["max_continuous_s"] for b in AdaptiveReport(p).buckets.values()),60)
            self.assertIsNone(AdaptiveReport(p).snapshot()["current_streak"])
            d=json.loads(p.read_text())
            for b in d["buckets"].values():
                del b["max_continuous_s"]
                del b["beyond_hour_s"]
            p.write_text(json.dumps(d))
            restored=AdaptiveReport(p)
            self.assertEqual(sum(b["running_s"] for b in restored.buckets.values()),60)
            self.assertEqual(sum(b["max_continuous_s"] for b in restored.buckets.values()),0)

    def test_bounded_events(self):
        r=AdaptiveReport()
        for i in range(600):
            r.event("issued","auto",str(i),wall=i)
        self.assertEqual(len(r.events),512)
        self.assertEqual(r.events[0]["detail"],"88")

if __name__=="__main__":
    unittest.main()
