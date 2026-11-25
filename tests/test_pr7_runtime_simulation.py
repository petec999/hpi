"""End-to-end simulated MQTT broker test of the PR7 service entrypoint.

Runs the actual main() with a fake paho client, fake publisher/subscriber,
retained Home Assistant discovery configs, and fresh HaierPi telemetry.
No external MQTT broker or heat pump required.
"""
import json
import os
import sys
import types
import unittest
from unittest.mock import patch

from diagnostics.mqtt_circuit_bridge import SOURCE_IDS, METRIC_UNITS, main

TOPICS = {
    "twi": ("sim/twitwo", "{{ value_json[0] | float }}"),
    "two": ("sim/twitwo", "{{ value_json[1] | float }}"),
    "tao": ("sim/tao", ""),
    "tsat_ps_actual": ("sim/ps_sat", "{{ value_json[1] | float }}"),
    "tsat_pd_actual": ("sim/pd_sat", "{{ value_json[1] | float }}"),
    "td": ("sim/tdts", "{{ value_json[0] | float }}"),
    "ps_actual": ("sim/ps", "{{ value_json[1] | float }}"),
    "pd_actual": ("sim/pd", "{{ value_json[1] | float }}"),
    "compressor_actual_hz": ("sim/comp", "{{ value_json[1] | float }}"),
    "compressor_target_hz": ("sim/comp", "{{ value_json[0] | float }}"),
}
DATA = {
    "sim/twitwo": "[31,34]",
    "sim/tao": "2",
    "sim/ps_sat": "[-2,-2.5]",
    "sim/pd_sat": "[33,32.6]",
    "sim/tdts": "[47.1,10]",
    "sim/ps": "[0.6,0.6]",
    "sim/pd": "[2.2,2.2]",
    "sim/comp": "[55,40,5,220,35]",
}
BASE = "climate/haier"


class Done(Exception):
    pass


class FakeMessage:
    def __init__(self, topic, payload, retained=False):
        self.topic = topic
        self.payload = payload.encode() if isinstance(payload, str) else payload
        self.retain = retained


class FakeClient:
    instance = None

    def __init__(self, *args, **kwargs):
        type(self).instance = self
        self.sent = []
        self.subscriptions = []
        self.on_connect = None
        self.on_message = None
        self.on_disconnect = None

    def username_pw_set(self, *args):
        pass

    def will_set(self, *args, **kwargs):
        pass

    def connect(self, *args, **kwargs):
        pass

    def subscribe(self, topic, qos=1):
        self.subscriptions.append(topic)

    def publish(self, topic, payload, qos=1, retain=True):
        self.sent.append((topic, str(payload), retain))

    def loop_start(self):
        self.on_connect(self, None, {}, 0)
        # Retained MQTT Discovery config is expected and safe.
        for field, uid in SOURCE_IDS.items():
            topic, template = TOPICS[field]
            cfg = {"uniq_id": uid, "stat_t": topic, "val_tpl": template,
                   "unit_of_measurement": "MPa" if field in ("ps_actual", "pd_actual") else ""}
            self.on_message(self, None, FakeMessage(
                "homeassistant/sensor/example/config", json.dumps(cfg), True))
        for kind in ("r141", "r241"):
            self.on_message(self, None, FakeMessage(
                BASE + "/haierpi/" + kind + "_fresh", "online", True))
        self.on_message(self, None, FakeMessage(
            BASE + "/haierpi/connected", "online", True))
        # Retained samples are intentionally not fresh.
        for topic, payload in DATA.items():
            self.on_message(self, None, FakeMessage(topic, payload, True))
        for topic, payload in DATA.items():
            self.on_message(self, None, FakeMessage(topic, payload, False))

    def loop_stop(self):
        pass

    def disconnect(self):
        pass


class RuntimeSimulationTests(unittest.TestCase):
    def test_complete_service_cycle(self):
        fake_paho = types.ModuleType("paho")
        fake_mqtt = types.ModuleType("paho.mqtt")
        fake_client = types.ModuleType("paho.mqtt.client")
        fake_client.Client = FakeClient
        fake_paho.mqtt = fake_mqtt
        fake_mqtt.client = fake_client
        with patch.dict(sys.modules, {
            "paho": fake_paho,
            "paho.mqtt": fake_mqtt,
            "paho.mqtt.client": fake_client,
        }), patch.dict(os.environ, {"HPI_TOPIC": BASE}, clear=False), patch(
            "diagnostics.mqtt_circuit_bridge.time.sleep", side_effect=Done):
            with self.assertRaises(Done):
                main()

        messages = FakeClient.instance.sent
        discoveries = [(t, json.loads(v)) for t, v, _ in messages
                       if t.startswith("homeassistant/sensor/haierpi_pr7/")]
        self.assertEqual(len(discoveries), len(METRIC_UNITS))
        published = {t: v for t, v, _ in messages
                     if t.startswith(BASE + "/diagnostics/circuit/")}
        self.assertEqual(published[BASE + "/diagnostics/circuit/water_delta_t"], "3.0")
        self.assertEqual(published[BASE + "/diagnostics/circuit/saturation_lift"], "35.1")
        self.assertEqual(published[BASE + "/diagnostics/circuit/ambient_evaporating_approach"], "4.5")
        self.assertEqual(published[BASE + "/diagnostics/circuit/pressure_delta_mpa"], "1.6")
        self.assertEqual(published[BASE + "/diagnostics/circuit/compressor_frequency_error_hz"], "15.0")
        # Shutdown correctly announces unavailable.
        self.assertEqual(messages[-1][0], BASE + "/diagnostics/circuit/availability")
        self.assertEqual(messages[-1][1], "offline")
        self.assertTrue(any(t == BASE + "/diagnostics/circuit/availability"
                            and v == "online" for t, v, _ in messages))


if __name__ == "__main__":
    unittest.main()
