import importlib.util
from pathlib import Path
import unittest

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("watchdog", root/"tools/install-mqtt-watchdog.py")
wd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wd)

SOURCE = """def mqtt_snapshot_tick():
    global _mqtt_snapshot_last_ts
    now = 0
    _mqtt_snapshot_last_ts = now
    mqtt_publish_snapshot()

def on_message(client, userdata, msg):  # vendor comment with trailing spaces   
    return None

def connect_mqtt():
    while True:
        try:
            rc = cl.loop(timeout=1.0)
        except Exception:
            pass
"""

class WatchdogPatchTests(unittest.TestCase):
    def test_patch_compiles_and_is_idempotent(self):
        patched = wd.patch(SOURCE)
        compile(patched, "test-core", "exec")
        self.assertIn("    mqtt_publish_snapshot()\n    _haierpi_watchdog_tick()", patched)
        self.assertIn('if msg.topic == str(mqtt_topic) + "/haierpi/watchdog_heartbeat":', patched)
        self.assertEqual(wd.patch(patched), patched)

    def test_refuses_unrecognized_layout(self):
        with self.assertRaises(RuntimeError):
            wd.patch(SOURCE.replace("mqtt_publish_snapshot()", "something_else()"))
        with self.assertRaises(RuntimeError):
            wd.patch(SOURCE.replace("on_message(client", "other(client"))

    def test_comment_optional(self):
        patched = wd.patch(SOURCE.replace("  # vendor comment with trailing spaces   ", ""))
        compile(patched, "test-core", "exec")

    def test_upgrade_v1(self):
        old = SOURCE.replace("def mqtt_snapshot_tick():",
            "# HOME-IOT MQTT WATCHDOG v1\ndef _haierpi_watchdog_worker():\n    pass\n\n"
            "def mqtt_snapshot_tick():", 1)
        old = old.replace("    mqtt_publish_snapshot()\n",
            "    mqtt_publish_snapshot()\n    _haierpi_watchdog_tick()\n", 1)
        old = old.replace("    return None\n",
            '    if msg.topic == str(mqtt_topic) + "/haierpi/watchdog_heartbeat":\n'
            '        return\n    return None\n', 1)
        self.assertEqual(wd.patch(old), wd.patch(SOURCE))

    def test_missing_worker_refuses(self):
        with self.assertRaises(RuntimeError):
            wd.patch(SOURCE.replace("cl.loop(timeout=1.0)", "cl.loop()"))
