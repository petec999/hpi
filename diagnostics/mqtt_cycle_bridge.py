"""Optional MQTT sidecar for PR #6. Does not modify heat pump controls.

Requires paho-mqtt and freshness topics from upstream PR #4.
Configure HA MQTT broker credentials via environment variables.
"""
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
import json
import os
import time

from diagnostics.cycle_counter import CycleCounter


def parse_defrost(payload):
    value = payload.strip().lower()
    if value in ("on", "true", "1", "yes"):
        return True
    if value in ("off", "false", "0", "no"):
        return False
    raise ValueError("Unknown defrost state")


def parse_actual_hz(payload):
    values = json.loads(payload)
    # PyHaier GetCompInfo order: fset, fact, current, voltage, temperature.
    if not isinstance(values, list) or len(values) < 2:
        raise ValueError("Invalid compressor data")
    value = values[1]
    if type(value) not in (int, float):
        raise ValueError("Invalid Hz")
    return float(value)


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


def main():
    try:
        import paho.mqtt.client as mqtt
    except ImportError as exc:
        raise SystemExit("Install paho-mqtt first") from exc

    base = os.environ.get("HPI_TOPIC", "climate/haier").rstrip("/")
    host = os.environ.get("HPI_MQTT_HOST", "127.0.0.1")
    port = int(os.environ.get("HPI_MQTT_PORT", "1883"))
    comp_topic = os.environ.get("HPI_COMP_TOPIC", base + "/details/compinfo/state")
    defrost_topic = os.environ.get("HPI_DEFROST_TOPIC", base + "/details/defrost/state")
    tz = ZoneInfo(os.environ.get("HPI_TZ", "Europe/Warsaw"))
    storage = Path(os.environ.get("HPI_COUNTER_FILE",
                "/var/lib/haierpi/cycle_counters.json"))
    counters = CycleCounter(storage)
    sample = {"comp": None, "defrost": None,
              "r141": False, "r241": False, "connected": False}
    received_at = {"comp": 0.0, "defrost": 0.0}
    last_tick = 0.0
    discovery_prefix = os.environ.get("HPI_DISCOVERY_PREFIX", "homeassistant")
    freshness_ttl = float(os.environ.get("HPI_SAMPLE_TTL", "120"))
    if not 0 < freshness_ttl <= 180:
        raise ValueError("HPI_SAMPLE_TTL must be within 0..180 seconds")

    client = mqtt.Client(client_id="haierpi-pr6-counters")
    username = os.environ.get("HPI_MQTT_USERNAME")
    if username:
        client.username_pw_set(username, os.environ.get("HPI_MQTT_PASSWORD"))
    availability = base + "/diagnostics/counters/available"
    topics = {
        comp_topic: "comp",
        defrost_topic: "defrost",
        base + "/haierpi/r141_fresh": "r141",
        base + "/haierpi/r241_fresh": "r241",
        base + "/haierpi/connected": "connected",
    }
    client.will_set(availability, "offline", qos=1, retain=True)

    def publish_discovery():
        for key, (name, unit) in METRICS.items():
            cfg = {
                "name": name,
                "unique_id": "HaierPi_PR6_" + key,
                "state_topic": base + "/diagnostics/counters/" + key,
                "availability_topic": availability,
                "payload_available": "online",
                "payload_not_available": "offline",
                "device": {"identifiers": ["haierpi_pr6_diagnostics"],
                           "name": "HaierPi Diagnostics"},
                "icon": "mdi:counter" if unit is None else "mdi:timer-outline",
            }
            if unit:
                cfg["unit_of_measurement"] = unit
            client.publish(
                discovery_prefix + "/sensor/haierpi_pr6/" + key + "/config",
                json.dumps(cfg), qos=1, retain=True)

    def on_connect(client, userdata, flags, rc):
        if rc != 0:
            return
        # Reset availability: retained MQTT readings alone are not live data.
        sample.update(comp=None, defrost=None, r141=False,
                      r241=False, connected=False)
        received_at.update(comp=0.0, defrost=0.0)
        for topic in topics:
            client.subscribe(topic, qos=1)
        publish_discovery()
        client.publish(availability, "online", qos=1, retain=True)

    def on_disconnect(client, userdata, rc):
        sample.update(r141=False, r241=False, connected=False)

    def on_message(client, userdata, msg):
        key = topics.get(msg.topic)
        if key is None:
            return
        try:
            payload = msg.payload.decode("utf-8")
            if key == "comp":
                sample[key] = parse_actual_hz(payload)
                received_at[key] = time.monotonic()
            elif key == "defrost":
                sample[key] = parse_defrost(payload)
                received_at[key] = time.monotonic()
            else:
                sample[key] = payload.strip().lower() == "online"
        except (UnicodeError, ValueError, TypeError, json.JSONDecodeError):
            if key in ("comp", "defrost"):
                sample[key] = None

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    client.connect(host, port, keepalive=60)
    client.loop_start()
    try:
        while True:
            now = time.monotonic()
            if now - last_tick >= 30:
                last_tick = now
                fresh = (sample["connected"] and sample["r141"] and sample["r241"]
                    and all(now - received_at[key] <= freshness_ttl
                            for key in ("comp", "defrost")))
                results = counters.observe(datetime.now(tz),
                    compressor_hz=sample["comp"], defrost=sample["defrost"],
                    r141_fresh=bool(fresh), r241_fresh=bool(fresh))
                for key in METRICS:
                    client.publish(base + "/diagnostics/counters/" + key,
                                   str(results[key]), qos=1, retain=True)
            time.sleep(1)
    finally:
        client.publish(availability, "offline", qos=1, retain=True)
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
