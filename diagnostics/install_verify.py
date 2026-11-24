"""Verify real MQTT diagnostic availability after installation.

Connects to the configured broker, observes PR6 and PR7 availability,
and confirms PR8 SQLite database exists. Never publishes commands.
"""
import argparse
from pathlib import Path
import sys
import threading
import time


def read_env(path):
    """Parse systemd EnvironmentFile without executing shell expressions."""
    result = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError("Malformed MQTT configuration")
        key, value = line.split("=", 1)
        result[key] = value.strip().strip('"').strip("'")
    return result


def verify(env_path, timeout=180, check_db=True):
    import paho.mqtt.client as mqtt
    env = read_env(env_path)
    base = env.get("HPI_TOPIC", "climate/haier").rstrip("/")
    host = env.get("HPI_MQTT_HOST", "127.0.0.1")
    port = int(env.get("HPI_MQTT_PORT", "1883"))
    statuses = {
        base + "/diagnostics/counters/available": False,
        base + "/diagnostics/pr7/availability": False,
    }
    lock = threading.Lock()
    connected = threading.Event()
    done = threading.Event()

    client = mqtt.Client(client_id="haierpi-integrated-verifier")
    if env.get("HPI_MQTT_USERNAME"):
        client.username_pw_set(env["HPI_MQTT_USERNAME"],
                               env.get("HPI_MQTT_PASSWORD"))
    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            connected.set()
            for topic in statuses:
                client.subscribe(topic, qos=1)

    def on_message(client, userdata, msg):
        if msg.topic in statuses:
            with lock:
                statuses[msg.topic] = msg.payload.strip().lower() == b"online"
                if all(statuses.values()):
                    done.set()

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(host, port, 60)
    client.loop_start()
    try:
        if not connected.wait(min(15.0, timeout)):
            raise RuntimeError("MQTT broker connection/authentication failed")
        if not done.wait(timeout):
            raise RuntimeError("Diagnostic sensors did not become available: " +
                               str(statuses))
        if check_db:
            # Running SQLite historian should have created the DB on startup.
            database = Path("/var/lib/haierpi/history.sqlite")
            if not database.is_file():
                raise RuntimeError("PR8 SQLite database missing: " + str(database))
        return True
    finally:
        client.loop_stop()
        client.disconnect()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", required=True)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--no-db", action="store_true")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("Timeout must be positive")
    verify(args.env, args.timeout, check_db=not args.no_db)
    print("PASS: PR6 and PR7 MQTT online, PR8 database initialized")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        sys.exit("FAIL: " + str(exc))
