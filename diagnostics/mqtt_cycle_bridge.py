try:
    from .source_topics import live_state_topic
except ImportError:
    from source_topics import live_state_topic

"""PR6: read-only MQTT diagnostic sidecar, auto-discovers HaierPi source sensors.

Prerequisites: HaierPi MQTT discovery, R141/R241 availability (fix #4).
Never publishes Haier control commands.
"""
from datetime import datetime
from zoneinfo import ZoneInfo
import json
import math
import os
from pathlib import Path
import re
import time

try:
    from .cycle_counter import CycleCounter
except ImportError:
    from cycle_counter import CycleCounter

METRICS = {
    "compressor_starts": ("Compressor starts today", None),
    "compressor_seconds": ("Compressor run today", "s"),
    "compressor_completed_cycles": ("Completed compressor cycles today", None),
    "compressor_last_cycle_seconds": ("Last compressor cycle", "s"),
    "defrost_starts": ("Defrost starts today", None),
    "defrost_seconds": ("Defrost run today", "s"),
    "defrost_completed_cycles": ("Completed defrost cycles today", None),
    "defrost_last_cycle_seconds": ("Last defrost cycle", "s"),
}
SOURCE_IDS = {"comp": "HaierPi_Compfact", "defrost": "HaierPi_Defrost"}
_INDEX = re.compile(r"value_json\s*\[\s*(\d+)\s*\]")
_KEY = re.compile(r"value_json\s*\.\s*([A-Za-z_]\w*)")
_NUMBER = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")


def extract(payload, template=""):
    raw = payload.decode("utf-8") if isinstance(payload, bytes) else str(payload)
    template = (template or "").strip()
    if not template or template in ("{{ value }}", "{{value}}"):
        return raw.strip()
    indices, keys = _INDEX.findall(template), _KEY.findall(template)
    if len(indices) + len(keys) != 1:
        raise ValueError("Unsupported discovery template")
    data = json.loads(raw)
    if indices:
        if not isinstance(data, list):
            raise ValueError("Expected JSON list")
        return data[int(indices[0])]
    if not isinstance(data, dict):
        raise ValueError("Expected JSON dict")
    return data[keys[0]]


def parse_defrost(value, payload_on="ON", payload_off="OFF"):
    value = str(value).strip().lower()
    if value in (str(payload_on).lower(), "true", "1", "on", "yes"):
        return True
    if value in (str(payload_off).lower(), "false", "0", "off", "no"):
        return False
    raise ValueError("Unknown defrost state")


def parse_actual_hz(value):
    if type(value) not in (int, float, str) or not _NUMBER.fullmatch(str(value).strip()):
        raise ValueError("Invalid compressor frequency")
    hz = float(value)
    if not math.isfinite(hz) or not 0 <= hz <= 250:
        raise ValueError("Out of range compressor Hz")
    return hz


class MQTTInput:
    def __init__(self, ttl=120):
        if not 0 < ttl <= 180:
            raise ValueError("TTL must be within 0..180 seconds")
        self.ttl = float(ttl)
        self.base = os.environ.get("HPI_TOPIC", "climate/haier").rstrip("/")
        self.topics = {}
        self.values = {}
        # Defrost is a retained MQTT status on live HaierPi. It may initialize
        # our baseline but must not be counted as a new defrost transition.
        self.retained_defrost_baseline = False
        self.health = {"r141": False, "r241": False, "connected": False}

    def discover(self, config):
        uid = config.get("uniq_id", config.get("unique_id"))
        key = next((k for k, v in SOURCE_IDS.items() if v == uid), None)
        if key is None:
            return None
        topic = live_state_topic(uid, config.get("stat_t", config.get("state_topic")), self.base)
        template = config.get("val_tpl", config.get("value_template", ""))
        if not isinstance(topic, str) or not topic or not isinstance(template, str):
            raise ValueError("Bad MQTT discovery configuration")
        self.topics[key] = (topic, template,
                            config.get("pl_on", config.get("payload_on", "ON")),
                            config.get("pl_off", config.get("payload_off", "OFF")))
        self.values.pop(key, None)
        if key == "defrost":
            self.retained_defrost_baseline = False
        return topic

    def update(self, topic, payload, *, retained=False, now=None):
        # The compressor MUST arrive live. HaierPi's retained defrost status
        # is usable only as an initial steady-state baseline when the separate
        # connected/r141/r241 MQTT freshness gates are all online.
        if retained and topic != self.topics.get("defrost", (None,))[0]:
            return
        if now is None:
            now = time.monotonic()
        for key, (src, template, on, off) in self.topics.items():
            if src != topic:
                continue
            try:
                item = extract(payload, template)
                value = parse_actual_hz(item) if key == "comp" else parse_defrost(item, on, off)
                self.values[key] = (value, now)
                if key == "defrost":
                    self.retained_defrost_baseline = bool(retained)
            except (ValueError, TypeError, IndexError, KeyError, json.JSONDecodeError):
                self.values.pop(key, None)
                if key == "defrost":
                    self.retained_defrost_baseline = False

    def availability(self, kind, payload):
        state = payload.decode() if isinstance(payload, bytes) else str(payload)
        self.health[kind] = state.strip().lower() == "online"
        if not self.health[kind]:
            self.values.clear()
            self.retained_defrost_baseline = False

    def current(self, now=None):
        now = time.monotonic() if now is None else now
        if (not all(self.health.values()) or set(self.topics) != set(SOURCE_IDS)
                or set(self.values) != set(SOURCE_IDS)):
            return None
        for key, (_, observed) in self.values.items():
            if key == "defrost" and self.retained_defrost_baseline:
                continue  # retained status is a baseline, not a periodic telemetry sample
            if not 0 <= now - observed <= self.ttl:
                return None
        return self.values["comp"][0], self.values["defrost"][0]

    def reset(self):
        self.values.clear()
        self.retained_defrost_baseline = False
        self.health = dict.fromkeys(self.health, False)


def main():
    try:
        import paho.mqtt.client as mqtt
    except ImportError as exc:
        raise SystemExit("Install paho-mqtt first") from exc

    base = os.environ.get("HPI_TOPIC", "climate/haier").rstrip("/")
    prefix = os.environ.get("HPI_DISCOVERY_PREFIX", "homeassistant").rstrip("/")
    state = MQTTInput(float(os.environ.get("HPI_SAMPLE_TTL", "120")))
    counters = CycleCounter(Path(os.environ.get(
        "HPI_COUNTER_FILE", "/var/lib/haierpi/cycle_counters.json")))
    zone = ZoneInfo(os.environ.get("HPI_TZ", "Europe/Warsaw"))
    output = base + "/diagnostics/counters"
    availability = output + "/available"
    availability_topics = {
        base + "/haierpi/r141_fresh": "r141",
        base + "/haierpi/r241_fresh": "r241",
        base + "/haierpi/connected": "connected",
    }
    client = mqtt.Client(client_id="haierpi-pr6-counters")
    username = os.environ.get("HPI_MQTT_USERNAME")
    if username:
        client.username_pw_set(username, os.environ.get("HPI_MQTT_PASSWORD"))
    client.will_set(availability, "offline", qos=1, retain=True)

    def publish_discovery():
        for key, (name, unit) in METRICS.items():
            cfg = {
                "name": name,
                "unique_id": "HaierPi_PR6_" + key,
                "state_topic": output + "/" + key,
                "availability_topic": availability,
                "payload_available": "online",
                "payload_not_available": "offline",
                "device": {"identifiers": ["haierpi_pr6_diagnostics"],
                           "name": "HaierPi Diagnostics"},
                "icon": "mdi:counter" if unit is None else "mdi:timer-outline",
            }
            if unit:
                cfg["unit_of_measurement"] = unit
            client.publish(prefix + "/sensor/haierpi_pr6/" + key + "/config",
                           json.dumps(cfg), qos=1, retain=True)

    def on_connect(client, userdata, flags, rc):
        if rc != 0:
            return
        state.reset()
        client.subscribe(prefix + "/sensor/#", qos=1)
        client.subscribe(prefix + "/binary_sensor/#", qos=1)
        for topic in availability_topics:
            client.subscribe(topic, qos=1)
        for src, *_ in state.topics.values():
            client.subscribe(src, qos=1)
        publish_discovery()
        client.publish(availability, "offline", qos=1, retain=True)

    def on_disconnect(client, userdata, rc):
        state.reset()

    def on_message(client, userdata, msg):
        if msg.topic in availability_topics:
            state.availability(availability_topics[msg.topic], msg.payload)
        elif msg.topic.startswith(prefix + "/") and msg.topic.endswith("/config"):
            try:
                cfg = json.loads(msg.payload)
                if not isinstance(cfg, dict):
                    return
                topic = state.discover(cfg)
                if topic:
                    client.subscribe(topic, qos=1)
            except (ValueError, TypeError, json.JSONDecodeError):
                pass
        else:
            state.update(msg.topic, msg.payload, retained=bool(msg.retain))

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    client.connect(os.environ.get("HPI_MQTT_HOST", "127.0.0.1"),
                   int(os.environ.get("HPI_MQTT_PORT", "1883")), keepalive=60)
    client.loop_start()
    try:
        while True:
            live = state.current()
            result = counters.observe(
                datetime.now(zone), compressor_hz=live[0] if live else None,
                defrost=live[1] if live else None,
                r141_fresh=live is not None, r241_fresh=live is not None)
            for key in METRICS:
                client.publish(output + "/" + key, str(result[key]), qos=1, retain=True)
            client.publish(availability, "online" if live else "offline",
                           qos=1, retain=True)
            time.sleep(30)
    finally:
        client.publish(availability, "offline", qos=1, retain=True)
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
