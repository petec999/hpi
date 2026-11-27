import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from adaptive.regulator import OperationMonitor, Sample

def sample(t,active=False,**kw):
    hz=30 if active else 0
    return replace(Sample(t,32,30,34,hz,hz,"eco",False,active,False,True),**kw)

class OperationTests(unittest.TestCase):
    def test_split_quarter_and_coverage(self):
        m=OperationMonitor()
        for t,wall,active in [(0,870,False),(30,900,True),(60,930,True),(90,960,False)]:
            m.observe(sample(t,active),wall,True)
        d=m.summary(1800)
        self.assertEqual(d["coverage_s"],90)
        self.assertEqual(d["compressor_s"],60)
        self.assertEqual(d["states"]["co_idle"],30)
        self.assertEqual(d["states"]["co_run"],60)
        self.assertEqual(d["starts"],1)
        self.assertEqual(d["co_starts"],1)
        self.assertEqual(d["missing_s"],86400-90)
        self.assertEqual(m.summary(930)["coverage_s"],30)

    def test_defrost_dhw_and_missing_not_idle(self):
        m=OperationMonitor()
        for t,s in [(0,sample(0,True)),(30,sample(30,True,defrost=True)),(60,sample(60,True,dhw=True)),(90,sample(90,False)),(240,sample(240,False))]:
            m.observe(s,900+t,True)
        d=m.summary(1800)
        self.assertEqual(d["coverage_s"],90)
        self.assertEqual(d["states"]["defrost"],30)
        self.assertEqual(d["defrost_starts"],1)
        self.assertEqual(d["states"]["dhw"],30)
        self.assertEqual(d["states"]["co_idle"],0)

    def test_persistence_no_bridge_across_restart(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"operation.json"
            m=OperationMonitor(p)
            m.observe(sample(0),900,True)
            m.observe(sample(30,True),930,True)
            m.save_if_due(30)
            n=OperationMonitor(p)
            self.assertEqual(n.rows,m.rows)
            n.observe(sample(60),960,True)
            self.assertEqual(n.summary(1800)["coverage_s"],30)

    def test_clock_jump_not_counted(self):
        m=OperationMonitor()
        m.observe(sample(0),900,True)
        m.observe(sample(30),945,True)
        self.assertEqual(m.summary(1800)["coverage_s"],0)
