import os
from pathlib import Path
import runpy
import tempfile
import unittest

P=runpy.run_path("tools/install-1454-core.py")
CORE=Path(os.environ["STABLE_ROOT"])

class Combined(unittest.TestCase):
    def test_clean_and_upgrade(self):
        raw=(CORE/"main.py").read_text()
        gpio=(CORE/"HPi/GPIO.py").read_text()
        wd=P["WD"]["patch"](raw)
        for source in (raw,wd,P["MQTT"]["patch"](wd)):
            for g in (gpio,P["GPIO"]["patch_gpio"](gpio)):
                with self.subTest(watchdog=source!=raw,gpio=g!=gpio):
                    with tempfile.TemporaryDirectory() as td:
                        root=Path(td)
                        (root/"HPi").mkdir()
                        (root/"main.py").write_text(source)
                        (root/"HPi/GPIO.py").write_text(g)
                        pending=P["plan"](root)
                        self.assertEqual((root/"main.py").read_text(),source)
                        for path,old,new in pending:
                            path.write_bytes(new)
                        self.assertEqual(P["plan"](root),[])
                        text=(root/"main.py").read_text()
                        self.assertIn(P["MQTT"]["NEW_EXTERNAL"],text)
                        self.assertIn("GPIO.setup(modbuspin, GPIO.OUT, initial=GPIO.LOW)",text)
                        self.assertIn("# HOME-IOT MQTT WATCHDOG v2",text)
                        self.assertIn(P["MQTT"]["RECONNECT_MARK"],text)
    def test_unknown_gpio_refused_without_writes(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root/"HPi").mkdir()
            raw=(CORE/"main.py").read_bytes()
            (root/"main.py").write_bytes(raw)
            (root/"HPi/GPIO.py").write_text("def setup(pin, action): pass\n")
            with self.assertRaises(ValueError):
                P["plan"](root)
            self.assertEqual((root/"main.py").read_bytes(),raw)

if __name__=="__main__":
    unittest.main()
