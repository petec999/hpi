"""Resolve MQTT Discovery references to the original state topics.

Live inspection of HaierPi on 2026-11-24 confirmed active fresh values on
climate/haier/haierunit/... for all 11 required PR6/PR7 sensors.
An earlier attempt to unconditionally redirect those topics to /details/...
prevented both diagnostic bridges from seeing their input streams.

Use the retained Home Assistant MQTT Discovery topic as published, not a
speculative equivalent. Do not change sensor state topics silently.
"""


def live_state_topic(uid, discovery_topic, base):
    """Return the actual state_topic advertised by HaierPi MQTT Discovery."""
    return discovery_topic
