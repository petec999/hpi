import unittest
from unittest.mock import patch
from pathlib import Path
import tempfile
from adaptive.live_runtime import Runtime

class HeaterReadOnlyTest(unittest.TestCase):
    def test_no_writer_and_marker_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/".adaptive-heater-owned-v1"
            p.write_text("A04\n")
            writes=[]
            r=Runtime({"set_newframe":lambda *a:writes.append(a)},Path(td)/"learning.json")
            for name in ("heater_request","heater_write","heater_tick","heater_mqtt"):
                self.assertFalse(hasattr(r,name))
            with patch("adaptive.live_runtime.time.monotonic",return_value=100):
                r.note("R141",[0,0,0,256]+[0]*12)
                r.observe_heater(100)
                self.assertTrue(r.heater_view()["state"])
                self.assertTrue(r.heater_view()["previous_request_marker"])
            self.assertTrue(p.exists())
            self.assertEqual(writes,[])
