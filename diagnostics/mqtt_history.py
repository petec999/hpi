try:
    from .source_topics import live_state_topic
except ImportError:
    from source_topics import live_state_topic

"""PR #8: MQTT history collector for HaierPi, PR6 and PR7 diagnostics.

Subscribe via retained HA MQTT Discovery, persist only numeric readings and
selected ON/OFF state transitions. No commands are published to the heat pump.
"""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
import os
import re
import time

try:
    from .history_store import HistoryStore
except ImportError:
    from history_store import HistoryStore

_INDEX = re.compile(r"value_json\s*\[\s*(\d+)\s*\]")
_KEY = re.compile(r"value_json\s*\.\s*([A-Za-z_]\w*)")
_NUM = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
_STATES = {"on", "off", "online", "offline", "heat", "cool", "idle",
           "defrost", "true", "false", "0", "1"}

# Only a finite number of curated diagnostic state transitions may be logged.
EVENT_IDS = {"HaierPi_Defrost", "HaierPi_Pump", "HaierPi_3wayvalve",
             "HaierPi_R141Fresh", "HaierPi_R241Fresh", "HaierPi_Error",
             "HaierPi_LastError", "HaierPi_Archerror"}


def parse_numeric(raw, template):
    value = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
    template = (template or "").strip()
    if template in ("", "{{ value }}", "{{value}}"):
        value = value.strip()
    else:
        m = _INDEX.search(template)
        k = _KEY.search(template)
        if bool(m) == bool(k):
            raise ValueError("Unsupported JSON template")
        data = json.loads(value)
        value = data[int(m.group(1))] if m else data[k.group(1)]
    if type(value) not in (str, int, float) or not _NUM.fullmatch(str(value).strip()):
        raise ValueError("Invalid numeric payload")
    import math
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Nonfinite measurement")
    return result


class HistoryCollector:
    def __init__(self, store, base="climate/haier", minimum_interval=60):
        if minimum_interval < 1:
            raise ValueError("Sampling interval must be positive")
        self.store = store
        self.base = base.rstrip("/")
        self.interval = float(minimum_interval)
        self.definitions = {}
        self.last_sample = {}
        self.last_event = {}
        self.topic_index = defaultdict(set)

    def discover(self, definition):
        uid = definition.get("uniq_id", definition.get("unique_id"))
        topic = live_state_topic(uid, definition.get("stat_t", definition.get("state_topic")), self.base)
        if (not isinstance(uid, str) or not uid.startswith("HaierPi_")
                or not isinstance(topic, str) or not topic.startswith(self.base + "/")):
            return None
        template = definition.get("val_tpl", definition.get("value_template", ""))
        unit = definition.get("unit_of_measurement", definition.get("unit_of_meas"))
        if not isinstance(template, str):
            return None
        old = self.definitions.get(uid)
        if old is not None:
            self.topic_index[old[0]].discard(uid)
        self.definitions[uid] = (topic, template, unit)
        self.topic_index[topic].add(uid)
        return topic

    def receive(self, topic, payload, *, retained=False, timestamp=None, monotonic=None):
        # MQTT retained messages cannot be interpreted as fresh measurements
        # or as new state transitions after reconnect.
        if retained:
            return
        if monotonic is None:
            monotonic = time.monotonic()
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)
        for uid in self.topic_index.get(topic, ()):
            _, template, unit = self.definitions[uid]
            if uid in EVENT_IDS:
                # Avoid turning unknown values or credentials into event data.
                state = payload.decode("utf-8").strip().lower() if isinstance(payload, bytes) else str(payload).strip().lower()
                if state not in _STATES:
                    continue
                prior = self.last_event.get(uid)
                if prior is not None and prior != state:
                    self.store.event("state_change", uid, prior, state, timestamp)
                self.last_event[uid] = state
                continue
            previous = self.last_sample.get(uid)
            if previous is not None and 0 <= monotonic - previous < self.interval:
                continue
            try:
                value = parse_numeric(payload, template)
            except (ValueError, TypeError, IndexError, KeyError, json.JSONDecodeError):
                continue
            self.store.sample(uid, value, unit, timestamp)
            self.last_sample[uid] = monotonic

    def reset_session(self):
        # An MQTT disconnect creates an unknown observation interval.
        self.last_event.clear()
        self.last_sample.clear()


def run():
    parser = argparse.ArgumentParser(description="HaierPi SQLite telemetry journal")
    parser.add_argument("--export", choices=("samples", "events"))
    parser.add_argument("--output", help="Destination CSV file")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()
    database = os.environ.get("HPI_HISTORY_FILE", "/var/lib/haierpi/history.sqlite")
    store = HistoryStore(database)
    try:
        if args.summary:
            print(json.dumps(store.summary(), indent=2))
            return
        if args.export:
            if not args.output:
                parser.error("--export needs --output")
            print(store.export_csv(args.output, args.export))
            return
        import paho.mqtt.client as mqtt
        base = os.environ.get("HPI_TOPIC", "climate/haier").strip("/")
        prefix = os.environ.get("HPI_DISCOVERY_PREFIX", "homeassistant").strip("/")
        recorder = HistoryCollector(store, base=base,
            minimum_interval=int(os.environ.get("HPI_HISTORY_SAMPLE_SECONDS", "60")))
        client = mqtt.Client(client_id="haierpi-pr8-history")
        username = os.environ.get("HPI_MQTT_USERNAME")
        if username:
            client.username_pw_set(username, os.environ.get("HPI_MQTT_PASSWORD"))
        subscriptions = set()
        connected = {"up": False}

        def on_connect(client, userdata, flags, rc):
            if rc != 0:
                return
            recorder.reset_session()
            connected["up"] = True
            client.subscribe(prefix + "/sensor/#", qos=1)
            client.subscribe(prefix + "/binary_sensor/#", qos=1)
            for topic in subscriptions:
                client.subscribe(topic, qos=1)

        def on_disconnect(client, userdata, rc):
            connected["up"] = False
            recorder.reset_session()

        def on_message(client, userdata, msg):
            if msg.topic.endswith("/config") and msg.topic.startswith(prefix + "/"):
                try:
                    config = json.loads(msg.payload)
                    if not isinstance(config, dict):
                        return
                    topic = recorder.discover(config)
                    if topic and topic not in subscriptions:
                        subscriptions.add(topic)
                        client.subscribe(topic, qos=1)
                except (ValueError, UnicodeError, TypeError, json.JSONDecodeError):
                    return
            else:
                recorder.receive(msg.topic, msg.payload, retained=bool(msg.retain))

        client.on_connect = on_connect
        client.on_disconnect = on_disconnect
        client.on_message = on_message
        client.connect(os.environ.get("HPI_MQTT_HOST", "127.0.0.1"),
                       int(os.environ.get("HPI_MQTT_PORT", "1883")), 60)
        client.loop_start()
        last_prune = 0.0
        try:
            while True:
                now = time.monotonic()
                if now - last_prune > 3600:
                    store.prune(days=int(os.environ.get("HPI_HISTORY_RETENTION_DAYS", "90")))
                    last_prune = now
                time.sleep(1)
        finally:
            client.loop_stop()
            client.disconnect()
    finally:
        store.close()


if __name__ == "__main__":
    run()
