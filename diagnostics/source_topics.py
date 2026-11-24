"""Resolve HaierPi alpha13 MQTT Discovery references to live MQTT topics.

Some installations retain legacy /haierunit/... discovery configs while the
controller publishes fresh values under /details/... . Only known HaierPi
unique IDs with an observed detail-topic mapping are redirected.
"""
DETAILS = {
    "HaierPi_Twi": "twitwo",
    "HaierPi_Two": "twitwo",
    "HaierPi_Tao": "tao",
    "HaierPi_TSatPs_act": "tsatps",
    "HaierPi_TSatPd_act": "tsatpd",
    "HaierPi_Td": "tdts",
    "HaierPi_Ps_act": "pdps",
    "HaierPi_Pd_act": "pdps",
    "HaierPi_Compfact": "compinfo",
    "HaierPi_Compfset": "compinfo",
    "HaierPi_Defrost": "defrost",
}


def live_state_topic(uid, discovery_topic, base):
    """Keep working discovery links; redirect only known legacy mappings."""
    if not isinstance(discovery_topic, str):
        return discovery_topic
    base = base.rstrip("/")
    if (uid in DETAILS and
            discovery_topic.startswith(base + "/haierunit/")):
        return base + "/details/" + DETAILS[uid] + "/state"
    return discovery_topic
