"""Offline checks of installer MQTT readiness verification."""
import tempfile
from pathlib import Path
from unittest.mock import patch
import sys
import types
import unittest

from diagnostics.install_verify import read_env, verify


class FakeMQTT:
    def __init__(self, *args, **kwargs):
        self.on_connect = None
        self.on_message = None
        self.subscriptions = []
        self.payloads = []
        self.connected = False
    def username_pw_set(self, *args):
        pass
    def connect(self, *args):
        self.connected = True
    def subscribe(self, topic, qos=1):
        self.subscriptions.append(topic)
        payload = "online" if not FakeMQTT.force_offline else "offline"
        msg = types.SimpleNamespace(topic=topic, payload=payload.encode())
        self.on_message(self, None, msg)
    def loop_start(self):
        if self.connected:
            self.on_connect(self, None, {}, 0)
    def loop_stop(self):
        pass
    def disconnect(self):
        pass
    force_offline = False


class InstallVerificationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "mqtt.env"
        self.path.write_text("HPI_TOPIC=climate/haier\nHPI_MQTT_HOST=127.0.0.1\n")
        FakeMQTT.force_offline = False

    def mqtt_modules(self):
        paho = types.ModuleType("paho")
        mqtt_pkg = types.ModuleType("paho.mqtt")
        client_mod = types.ModuleType("paho.mqtt.client")
        client_mod.Client = FakeMQTT
        mqtt_pkg.client = client_mod
        paho.mqtt = mqtt_pkg
        return {"paho": paho, "paho.mqtt": mqtt_pkg, "paho.mqtt.client": client_mod}

    def test_environment_read(self):
        self.assertEqual(read_env(self.path)["HPI_MQTT_HOST"], "127.0.0.1")

    def test_online_sensors(self):
        with patch.dict(sys.modules, self.mqtt_modules()):
            self.assertTrue(verify(self.path, timeout=0.1, check_db=False))

    def test_offline_sensor_triggers_rollback_condition(self):
        FakeMQTT.force_offline = True
        with patch.dict(sys.modules, self.mqtt_modules()):
            with self.assertRaises(RuntimeError):
                verify(self.path, timeout=0.01, check_db=False)


if __name__ == "__main__":
    unittest.main()
