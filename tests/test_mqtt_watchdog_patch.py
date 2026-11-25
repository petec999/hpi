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


    def test_runtime_alarm_recovery_and_cooldown(self):
        import logging
        import sys
        from types import SimpleNamespace
        from unittest.mock import patch
        clock = [1000]
        published = {}
        posts = []
        mode = ["ok"]
        client = SimpleNamespace(is_connected=lambda: True)
        def publish(topic, value, **kwargs):
            published[topic] = value
            return SimpleNamespace(rc=0)
        client.publish = publish
        def get(*args, **kwargs):
            if mode[0] == "offline":
                raise TimeoutError()
            value = published.get("climate/test/haierpi/watchdog_heartbeat") if mode[0] == "ok" else "old"
            return SimpleNamespace(status_code=200, json=lambda: {"state":value})
        def post(url, **kwargs):
            posts.append((url, kwargs["json"]))
            return SimpleNamespace(status_code=200)
        scope = dict(logging=logging, client=client, mqtt_topic="climate/test", use_mqtt="1",
                     ha_mqtt_discovery_prefix="homeassistant", ha_mqtt_discovery="1",
                     mqtt_snapshot_interval_s=30,
                     config={"HOMEASSISTANT":{"HAADDR":"http://ha","HAPORT":"8123","KEY":"test"}})
        exec(wd.WATCHDOG, scope)
        scope["_wd_time"] = SimpleNamespace(monotonic=lambda:clock[0], time_ns=lambda:clock[0], sleep=lambda _:None)
        def tick(t):
            clock[0] = t
            scope["_wd_lock"].acquire()
            scope["_haierpi_watchdog_worker"]()
        with patch.dict(sys.modules, {"requests":SimpleNamespace(get=get, post=post)}):
            tick(1000)
            self.assertEqual(scope["_wd_status"], "ok")
            mode[0] = "offline"
            for t in (1030, 1060, 1090, 1120, 1150, 1180):
                tick(t)
            self.assertIsNone(scope["_wd_reconnect_request"])
            self.assertTrue(scope["_wd_status"].startswith("alarm:"))
            self.assertEqual(scope["_wd_failures"], 1)
            self.assertTrue(posts[-1][0].endswith("/create"))
            mode[0] = "mismatch"
            for t in (1210,1240,1270):
                tick(t)
            self.assertIs(scope["_wd_reconnect_request"], client)
            scope["_wd_reconnect_request"] = None
            tick(1300)
            self.assertIsNone(scope["_wd_reconnect_request"])
            mode[0] = "ok"
            tick(1330)
            self.assertEqual(scope["_wd_status"], "ok")
            self.assertEqual(scope["_wd_recoveries"], 1)
            self.assertTrue(posts[-1][0].endswith("/dismiss"))
