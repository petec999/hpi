"""PR6 simulated end-to-end MQTT service: discovery, transitions, persistence."""
import json
import os
import sys
import tempfile
import types
import unittest
from datetime import datetime as RealDatetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from diagnostics.mqtt_cycle_bridge import MQTTInput, METRICS, main


class StopSimulation(Exception):
    pass


class Msg:
    def __init__(self, topic, payload, retain=False):
        self.topic = topic
        self.payload = payload.encode() if isinstance(payload, str) else payload
        self.retain = retain


class FakeClient:
    instance = None

    def __init__(self, *args, **kwargs):
        type(self).instance = self
        self.sent = []
        self.subscriptions = []
        self.on_message = None
        self.on_connect = None

    def will_set(self, *args, **kwargs):
        pass

    def username_pw_set(self, *args, **kwargs):
        pass

    def connect(self, *args, **kwargs):
        pass

    def subscribe(self, topic, qos=1):
        self.subscriptions.append(topic)

    def publish(self, topic, payload, qos=1, retain=True):
        self.sent.append((topic, str(payload), retain))

    def deliver(self, topic, payload, retained=False):
        self.on_message(self, None, Msg(topic, payload, retained))

    def loop_start(self):
        self.on_connect(self, None, {}, 0)
        for uid, topic, template in [
            ("HaierPi_Compfact", "climate/haier/details/compinfo/state",
             "{{ value_json[1] | float }}"),
            ("HaierPi_Defrost", "climate/haier/actual/defrost",
             ""),
        ]:
            config = {"uniq_id": uid, "stat_t": topic, "val_tpl": template}
            self.deliver("homeassistant/binary_sensor/haier/config"
                         if uid.endswith("Defrost") else
                         "homeassistant/sensor/haier/config",
                         json.dumps(config), retained=True)
        for suffix in ("r141_fresh", "r241_fresh", "connected"):
            self.deliver("climate/haier/haierpi/" + suffix, "online", retained=True)
        self.deliver("climate/haier/details/compinfo/state", "[42,0,4,230,40]")
        self.deliver("climate/haier/actual/defrost", "OFF")

    def loop_stop(self):
        pass

    def disconnect(self):
        pass


class SimulatedClock:
    def __init__(self):
        self.value = 0
        self.start = RealDatetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)

    def now(self, zone):
        result = self.start + timedelta(seconds=self.value)
        return result.astimezone(zone)


class PR6IntegrationTests(unittest.TestCase):
    def test_parse_freshness_and_discovery(self):
        state = MQTTInput(120)
        self.assertEqual(state.discover({"uniq_id": "HaierPi_Compfact",
            "stat_t": "sample/comp", "val_tpl": "{{ value_json[1] | float }}"}),
            "sample/comp")
        state.discover({"uniq_id": "HaierPi_Defrost",
            "stat_t": "sample/defrost", "pl_on": "YES", "pl_off": "NO"})
        for name in ("r141", "r241", "connected"):
            state.availability(name, "online")
        state.update("sample/comp", "[50,40]", retained=True, now=100)
        self.assertIsNone(state.current(now=100))
        state.update("sample/comp", "[50,40]", now=100)
        state.update("sample/defrost", "YES", now=100)
        self.assertEqual(state.current(now=100), (40, True))
        self.assertIsNone(state.current(now=221))
        state.availability("r241", "offline")
        self.assertIsNone(state.current(now=105))

    def test_retained_defrost_is_baseline_not_fresh_compressor(self):
        state = MQTTInput(ttl=10)
        state.discover({"uniq_id": "HaierPi_Compfact",
                        "stat_t": "sample/comp",
                        "val_tpl": "{{ value_json[1] | float }}"})
        state.discover({"uniq_id": "HaierPi_Defrost",
                        "stat_t": "sample/defrost"})
        for name in ("r141", "r241", "connected"):
            state.availability(name, "online")
        state.update("sample/defrost", "off", retained=True, now=100)
        self.assertIsNone(state.current(now=101))  # no live compressor yet
        state.update("sample/comp", "[40,40]", retained=True, now=100)
        self.assertIsNone(state.current(now=101))
        state.update("sample/comp", "[40,40]", now=105)
        self.assertEqual(state.current(now=106), (40.0, False))
        state.update("sample/comp", "[40,40]", now=130)
        self.assertEqual(state.current(now=131), (40.0, False))
        state.availability("r141", "offline")
        self.assertIsNone(state.current(now=132))
        state.availability("r141", "online")
        self.assertIsNone(state.current(now=133))  # baseline invalidated

    def test_simulated_runtime_mqtt_ha_and_restart(self):
        fake_paho = types.ModuleType("paho")
        mqtt_pkg = types.ModuleType("paho.mqtt")
        client_mod = types.ModuleType("paho.mqtt.client")
        client_mod.Client = FakeClient
        fake_paho.mqtt = mqtt_pkg
        mqtt_pkg.client = client_mod
        clock = SimulatedClock()
        ticks = [0]

        def step(seconds):
            ticks[0] += 1
            clock.value += seconds
            mqtt = FakeClient.instance
            if ticks[0] == 1:  # compressor OFF -> ON
                mqtt.deliver("climate/haier/details/compinfo/state", "[60,40,4,230,40]")
            elif ticks[0] == 2:  # defrost OFF -> ON
                mqtt.deliver("climate/haier/actual/defrost", "ON")
            elif ticks[0] == 3:  # keep both ON for another measurement interval
                mqtt.deliver("climate/haier/details/compinfo/state", "[60,40,4,230,40]")
                mqtt.deliver("climate/haier/actual/defrost", "ON")
            elif ticks[0] == 4:  # both ON -> OFF
                mqtt.deliver("climate/haier/details/compinfo/state", "[0,0,0,230,35]")
                mqtt.deliver("climate/haier/actual/defrost", "OFF")
            elif ticks[0] >= 5:
                raise StopSimulation()

        class ClockDatetime:
            @staticmethod
            def now(zone):
                return clock.now(zone)

        with tempfile.TemporaryDirectory() as temp:
            env = {"HPI_COUNTER_FILE": str(Path(temp) / "counts.json"),
                   "HPI_TOPIC": "climate/haier"}
            with patch.dict(sys.modules, {"paho": fake_paho,
                       "paho.mqtt": mqtt_pkg,
                       "paho.mqtt.client": client_mod}), patch.dict(
                       os.environ, env, clear=False), patch(
                       "diagnostics.mqtt_cycle_bridge.datetime", ClockDatetime), patch(
                       "diagnostics.mqtt_cycle_bridge.time.sleep", side_effect=step):
                with self.assertRaises(StopSimulation):
                    main()

            sent = FakeClient.instance.sent
            configs = [(t, json.loads(v)) for t, v, _ in sent
                       if "/haierpi_pr6/" in t and t.endswith("/config")]
            self.assertEqual(len(configs), 8)
            values = {t: v for t, v, _ in sent
                      if t.startswith("climate/haier/diagnostics/counters/")}
            self.assertEqual(values["climate/haier/diagnostics/counters/compressor_starts"], "1")
            self.assertEqual(values["climate/haier/diagnostics/counters/defrost_starts"], "1")
            self.assertEqual(values["climate/haier/diagnostics/counters/compressor_completed_cycles"], "1")
            self.assertEqual(values["climate/haier/diagnostics/counters/defrost_completed_cycles"], "1")
            self.assertEqual(values["climate/haier/diagnostics/counters/compressor_seconds"], "60.0")
            self.assertEqual(values["climate/haier/diagnostics/counters/defrost_seconds"], "30.0")
            saved = json.loads((Path(temp) / "counts.json").read_text())
            self.assertEqual(saved["daily"]["compressor_starts"], 1)
            self.assertEqual(saved["daily"]["defrost_starts"], 1)
            self.assertEqual(sent[-1][1], "offline")

    def test_invalid_data_fails_closed(self):
        state = MQTTInput()
        state.discover({"uniq_id": "HaierPi_Compfact", "stat_t": "c", "val_tpl": "{{ value_json[1] }}"})
        state.discover({"uniq_id": "HaierPi_Defrost", "stat_t": "d"})
        for key in state.health:
            state.availability(key, "online")
        state.update("c", "[40,55]")
        state.update("d", "unknown")
        self.assertIsNone(state.current())


if __name__ == "__main__":
    unittest.main()
