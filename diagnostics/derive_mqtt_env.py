"""Safely derive read-only diagnostic MQTT connection from existing HaierPi config.

No network writes; never modifies /opt/config.ini. Refuses ambiguous or
unsupported settings instead of silently using the wrong MQTT broker.
"""
import argparse
import configparser
from pathlib import Path
import os
import stat
import tempfile


def derive(path):
    config = configparser.ConfigParser(interpolation=None)
    if not config.read(path, encoding="utf-8"):
        raise ValueError("Cannot read existing HaierPi configuration")
    if not config.has_section("MQTT"):
        raise ValueError("Missing [MQTT] section in HaierPi config")
    section = config["MQTT"]
    if section.get("mqtt", "").strip() != "1":
        raise ValueError("HaierPi MQTT is disabled; not changing its setting automatically")
    if section.get("mqtt_ssl", "0").strip() not in ("0", "", "false", "False"):
        raise ValueError("MQTT TLS is enabled; diagnostic services need matching TLS configuration")
    host = section.get("address", "").strip()
    topic = section.get("main_topic", "").strip().strip("/")
    port_raw = section.get("port", "").strip()
    if not host or not topic:
        raise ValueError("Missing MQTT broker address or main_topic")
    if not port_raw.isdecimal() or not 1 <= int(port_raw) <= 65535:
        raise ValueError("Invalid MQTT broker port")
    if any(x in host for x in ("\n", "\r", " ", "=")) or any(x in topic for x in ("\n", "\r", " ", "=")):
        raise ValueError("Invalid MQTT host or topic")
    if config.get("HOMEASSISTANT", "ha_mqtt_discovery", fallback="0").strip() != "1":
        raise ValueError("MQTT Discovery is disabled; PR6/PR7 need it to find source sensors")
    prefix = config.get("HOMEASSISTANT", "ha_mqtt_discovery_prefix",
                        fallback="homeassistant").strip().strip("/") or "homeassistant"
    user = section.get("username", "")
    password = section.get("password", "")
    if any("\n" in v or "\r" in v for v in (prefix, user, password)):
        raise ValueError("Multiline MQTT credentials are not supported")
    if '"' in user or '"' in password or "\\" in user or "\\" in password:
        raise ValueError("Quoted MQTT credentials require manual configuration")
    # systemd EnvironmentFile supports quoted values containing whitespace,
    # without shell evaluation or exposure to command-line arguments.
    return {
        "HPI_MQTT_HOST": host,
        "HPI_MQTT_PORT": port_raw,
        "HPI_TOPIC": topic,
        "HPI_DISCOVERY_PREFIX": prefix,
        "HPI_MQTT_USERNAME": user,
        "HPI_MQTT_PASSWORD": password,
        "HPI_TZ": "Europe/Warsaw",
        "HPI_SAMPLE_TTL": "120",
    }


def save_env(settings, destination):
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=target.parent, prefix=".mqtt-diag-", text=True)
    try:
        os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write("# Auto-derived from existing HaierPi config; contains MQTT credentials.\n")
            for key, value in settings.items():
                if any(c in value for c in ("\n", "\r", "\0", '"', "\\")):
                    raise ValueError("Unsafe MQTT environment value")
                file.write(key + '="' + value + '"\n')
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp, target)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="/opt/config.ini")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    settings = derive(args.config)
    save_env(settings, args.output)
    print("MQTT configuration derived from existing HaierPi installation: "
          + settings["HPI_MQTT_HOST"] + ":" + settings["HPI_MQTT_PORT"]
          + ", topic=" + settings["HPI_TOPIC"])
    # Never print username/password.


if __name__ == "__main__":
    main()
