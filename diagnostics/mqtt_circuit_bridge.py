try:
    from .source_topics import live_state_topic
except ImportError:
    from source_topics import live_state_topic

"""MQTT Discovery-driven, read-only HaierPi PR7 telemetry sidecar.

Requires paho-mqtt and the circuit_telemetry.py module in this directory.
Does not issue control commands or touch the original HaierPi main.py.
"""
import json
import os
import re
import time
from datetime import datetime
from math import isfinite

try:
    from .circuit_telemetry import CircuitSample, derive
except ImportError:
    from circuit_telemetry import CircuitSample, derive


# Source entities already present in HaierPi alpha13/Stable MQTT Discovery.
SOURCE_IDS = {
    "twi": "HaierPi_Twi",
    "two": "HaierPi_Two",
    "tao": "HaierPi_Tao",
    "tsat_ps_actual": "HaierPi_TSatPs_act",
    "tsat_pd_actual": "HaierPi_TSatPd_act",
    "td": "HaierPi_Td",
    "ps_actual": "HaierPi_Ps_act",
    "pd_actual": "HaierPi_Pd_act",
    "compressor_actual_hz": "HaierPi_Compfact",
    "compressor_target_hz": "HaierPi_Compfset",
}
METRIC_UNITS = {
    "water_delta_t": "°C",
    "saturation_lift": "°C",
    "ambient_evaporating_approach": "°C",
    "discharge_condensing_gap": "°C",
    "pressure_delta_mpa": "MPa",
    "compressor_frequency_error_hz": "Hz",
}
METRIC_NAMES = {
    "water_delta_t": "CO water delta T",
    "saturation_lift": "Refrigerant saturation lift",
    "ambient_evaporating_approach": "Ambient evaporation approach",
    "discharge_condensing_gap": "Discharge condensing gap",
    "pressure_delta_mpa": "Refrigerant pressure delta",
    "compressor_frequency_error_hz": "Compressor frequency deviation",
}
_JSON_INDEX = re.compile(r"value_json\s*\[\s*(\d+)\s*\]")
_JSON_KEY = re.compile(r"value_json\s*\.\s*([A-Za-z_][A-Za-z_0-9]*)")
_SIMPLE_NUM = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")


def decode_value(payload, value_template):
    """Handle simple HA MQTT scalar and JSON index/property templates.

    Unsupported Jinja expressions fail closed rather than silently assigning
    a wrong temperature, pressure, or compressor frequency.
    """
    raw = payload.decode("utf-8") if isinstance(payload, bytes) else str(payload)
    template = (value_template or "").strip()
    if not template or template in ("{{ value }}", "{{value}}"):
        item = raw.strip()
    else:
        idx = _JSON_INDEX.findall(template)
        key = _JSON_KEY.findall(template)
        if len(idx) + len(key) != 1:
            raise ValueError("Unsupported HA MQTT value_template")
        value = json.loads(raw)
        if idx:
            if not isinstance(value, list):
                raise ValueError("Expected JSON list")
            item = value[int(idx[0])]
        else:
            if not isinstance(value, dict):
                raise ValueError("Expected JSON dictionary")
            item = value[key[0]]
    if type(item) not in (int, float, str):
        raise ValueError("Invalid telemetry value")
    if isinstance(item, str) and not _SIMPLE_NUM.fullmatch(item.strip()):
        raise ValueError("Not a numeric value")
    number = float(item)
    if not isfinite(number):
        raise ValueError("Nonfinite value")
    return number


class TelemetryState:
    def __init__(self, ttl=150):
        if not 0 < ttl <= 180:
            raise ValueError("TTL must be between 0 and 180 seconds")
        self.ttl = float(ttl)
        self.base = os.environ.get("HPI_TOPIC", "climate/haier").rstrip("/")
        self.mapping = {}
        self.values = {}
        self.availability = {"r141": False, "r241": False, "bridge": False}

    def configure(self, config):
        unique = config.get("uniq_id", config.get("unique_id"))
        if unique not in SOURCE_IDS.values():
            return False
        topic = live_state_topic(unique, config.get("stat_t", config.get("state_topic")), self.base)
        if not isinstance(topic, str) or not topic:
            raise ValueError("Source has no MQTT state topic")
        template = config.get("val_tpl", config.get("value_template", ""))
        if not isinstance(template, str):
            raise ValueError("Invalid source template")
        field = next(k for k, v in SOURCE_IDS.items() if v == unique)
        unit = config.get("unit_of_measurement", config.get("unit_of_meas", ""))
        if field in ("ps_actual", "pd_actual"):
            unit = (unit or "").strip().lower().replace(" ", "")
            if unit not in ("bar", "mpa", "kpa"):
                raise ValueError("Unknown pressure unit for " + field + ": " + repr(unit))
        else:
            unit = ""
        self.mapping[field] = (topic, template, unit)
        self.values.pop(field, None)
        return True

    def update_state(self, topic, payload, *, retained=False, now=None):
        # Retained MQTT payloads are historical, never proof of a new reading.
        if retained:
            return
        if now is None:
            now = time.monotonic()
        for field, (source_topic, value_template, unit) in self.mapping.items():
            if source_topic == topic:
                try:
                    value = decode_value(payload, value_template)
                    if field in ("ps_actual", "pd_actual"):
                        # Normalize the unit advertised by MQTT Discovery.
                        value *= {"bar": 0.1, "mpa": 1.0, "kpa": 0.001}[unit]
                    self.values[field] = (value, now)
                except (ValueError, KeyError, IndexError, TypeError, json.JSONDecodeError):
                    self.values.pop(field, None)

    def set_availability(self, key, payload):
        if key not in self.availability:
            raise ValueError("Unknown availability key")
        state = payload.decode() if isinstance(payload, bytes) else str(payload)
        self.availability[key] = state.strip().lower() == "online"
        if not self.availability[key]:
            self.values.clear()

    def calculate(self, *, now=None):
        if now is None:
            now = time.monotonic()
        if not all(self.availability.values()):
            return None
        if set(self.mapping) != set(SOURCE_IDS):
            return None
        if set(self.values) != set(SOURCE_IDS):
            return None
        if any(now - timestamp < 0 or now - timestamp > self.ttl
               for _, timestamp in self.values.values()):
            return None
        return derive(CircuitSample(**{
            field: self.values[field][0] for field in SOURCE_IDS
        }), r141_fresh=True, r241_fresh=True)


def main():
    try:
        import paho.mqtt.client as mqtt
    except ImportError as exc:
        raise SystemExit("Install paho-mqtt before starting the bridge") from exc

    prefix = os.environ.get("HPI_DISCOVERY_PREFIX", "homeassistant").strip("/")
    base = os.environ.get("HPI_TOPIC", "climate/haier").rstrip("/")
    state = TelemetryState(ttl=float(os.environ.get("HPI_SAMPLE_TTL", "150")))
    output = base + "/diagnostics/pr7"
    online = output + "/availability"
    source_topics = {}
    last_publish = None

    client = mqtt.Client(client_id="haierpi-pr7-telemetry")
    user = os.environ.get("HPI_MQTT_USERNAME")
    if user:
        client.username_pw_set(user, os.environ.get("HPI_MQTT_PASSWORD"))
    client.will_set(online, "offline", qos=1, retain=True)

    def publish_discovery():
        for metric, unit in METRIC_UNITS.items():
            cfg = {
                "name": METRIC_NAMES[metric],
                "unique_id": "HaierPi_PR7_" + metric,
                "state_topic": output + "/" + metric,
                "availability_topic": online,
                "payload_available": "online",
                "payload_not_available": "offline",
                "unit_of_measurement": unit,
                "state_class": "measurement",
                "device": {"identifiers": ["haierpi_pr7_diagnostics"],
                           "name": "HaierPi Advanced Diagnostics"},
            }
            client.publish(prefix + "/sensor/haierpi_pr7/" + metric + "/config",
                           json.dumps(cfg), qos=1, retain=True)

    availability_topics = {
        base + "/haierpi/r141_fresh": "r141",
        base + "/haierpi/r241_fresh": "r241",
        base + "/haierpi/connected": "bridge",
    }

    def on_connect(client, userdata, flags, rc):
        if rc != 0:
            return
        state.values.clear()
        state.availability = dict.fromkeys(state.availability, False)
        client.subscribe(prefix + "/sensor/#", qos=1)
        client.subscribe(base + "/haierpi/+", qos=1)
        for topic in set(item[0] for item in state.mapping.values()):
            client.subscribe(topic, qos=1)
        publish_discovery()
        client.publish(online, "offline", qos=1, retain=True)

    def on_disconnect(client, userdata, rc):
        state.values.clear()
        state.availability = dict.fromkeys(state.availability, False)

    def on_message(client, userdata, msg):
        if msg.topic in availability_topics:
            state.set_availability(availability_topics[msg.topic], msg.payload)
            return
        if msg.topic.startswith(prefix + "/sensor/") and msg.topic.endswith("/config"):
            try:
                cfg = json.loads(msg.payload)
                if state.configure(cfg):
                    topic = state.mapping[next(k for k, v in SOURCE_IDS.items() if v == cfg.get("uniq_id", cfg.get("unique_id")))][0]
                    if topic not in source_topics:
                        client.subscribe(topic, qos=1)
                        source_topics[topic] = True
            except (ValueError, TypeError, json.JSONDecodeError):
                pass
            return
        state.update_state(msg.topic, msg.payload, retained=bool(msg.retain))

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    client.connect(os.environ.get("HPI_MQTT_HOST", "127.0.0.1"),
                   int(os.environ.get("HPI_MQTT_PORT", "1883")), 60)
    client.loop_start()
    try:
        while True:
            results = state.calculate()
            if results is None:
                if last_publish is not False:
                    client.publish(online, "offline", qos=1, retain=True)
                    last_publish = False
            else:
                for metric, value in results.items():
                    client.publish(output + "/" + metric, str(value),
                                   qos=1, retain=True)
                client.publish(online, "online", qos=1, retain=True)
                last_publish = True
            time.sleep(30)
    finally:
        client.publish(online, "offline", qos=1, retain=True)
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
