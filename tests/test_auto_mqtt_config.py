"""Automatic MQTT config detection, including fail-closed cases."""
import configparser
import os
import stat
import tempfile
import unittest
from pathlib import Path
from diagnostics.derive_mqtt_env import derive, save_env


def config_file(root, mqtt="1", discovery="1", tls="0"):
    p = Path(root) / "config.ini"
    cfg = configparser.ConfigParser()
    cfg["MQTT"] = {
        "mqtt": mqtt, "address": "192.0.2.5", "port": "1883",
        "mqtt_ssl": tls, "main_topic": "climate/haier",
        "username": "haier_user", "password": "secure-pass-test",
    }
    cfg["HOMEASSISTANT"] = {
        "ha_mqtt_discovery": discovery,
        "ha_mqtt_discovery_prefix": "homeassistant",
    }
    with p.open("w") as f:
        cfg.write(f)
    return p


class AutoMQTTTests(unittest.TestCase):
    def test_detects_real_alpha13_keys_and_permissions(self):
        with tempfile.TemporaryDirectory() as root:
            settings = derive(config_file(root))
            self.assertEqual(settings["HPI_MQTT_HOST"], "192.0.2.5")
            self.assertEqual(settings["HPI_MQTT_PORT"], "1883")
            self.assertEqual(settings["HPI_TOPIC"], "climate/haier")
            self.assertEqual(settings["HPI_MQTT_USERNAME"], "haier_user")
            output = Path(root) / "generated.env"
            save_env(settings, output)
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
            self.assertIn('HPI_MQTT_PASSWORD="secure-pass-test"', output.read_text())
            # The original HaierPi configuration remains unchanged.
            self.assertIn("secure-pass-test", (Path(root) / "config.ini").read_text())

    def test_disabled_mqtt_fails_without_change(self):
        with tempfile.TemporaryDirectory() as root:
            p = config_file(root, mqtt="0")
            original = p.read_bytes()
            with self.assertRaisesRegex(ValueError, "disabled"):
                derive(p)
            self.assertEqual(p.read_bytes(), original)

    def test_disabled_discovery_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(ValueError, "Discovery"):
                derive(config_file(root, discovery="0"))

    def test_tls_fails_closed_when_sidecar_not_configured_for_it(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(ValueError, "TLS"):
                derive(config_file(root, tls="1"))

    def test_missing_broker_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            p = config_file(root)
            text = p.read_text().replace("address = 192.0.2.5", "address = ")
            p.write_text(text)
            with self.assertRaisesRegex(ValueError, "broker"):
                derive(p)


if __name__ == "__main__":
    unittest.main()
