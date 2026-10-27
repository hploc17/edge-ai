"""No secrets embedded. Python 3.6 compatible."""
import os
from urllib.parse import urlparse


def load_env_file(path):
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as stream:
        for line in stream:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def source_mode(value):
    value = str(value).lower()
    if value in ("video", "video_demo", "file"):
        return "video"
    if value == "csi":
        return "csi"
    raise ValueError("ANALYTICS_SOURCE must be video or csi; no automatic camera fallback")


def exact_topic(value):
    if not value or any(c in value for c in ("#", "+", "\0")):
        raise ValueError("MQTT topic must be exact: no # or +")
    return value


def mqtt_settings():
    edge = os.getenv("EDGE_ID", "edge-01")
    raw = os.getenv("MQTT_URL")
    if not raw:
        raw = "mqtts://%s:%s" % (os.getenv("MQTT_HOST", "localhost"), os.getenv("MQTT_PORT", "8883"))
    parsed = urlparse(raw)
    if parsed.scheme not in ("mqtt", "mqtts") or not parsed.hostname or parsed.username:
        raise ValueError("Use MQTT_URL=mqtts://host:8883 and separate credential variables")
    topics = [exact_topic(os.getenv(key, "traffic/%s/%s" % (edge, suffix)))
              for key, suffix in (("MQTT_COMMAND_TOPIC", "command"),
                                  ("MQTT_COMMAND_RESULT_TOPIC", "command-result"),
                                  ("MQTT_TELEMETRY_TOPIC", "telemetry"))]
    if len(set(topics)) != 3:
        raise ValueError("Command/result/telemetry topics must differ")
    return dict(host=parsed.hostname, port=parsed.port or (8883 if parsed.scheme == "mqtts" else 1883),
                tls=parsed.scheme == "mqtts", username=os.getenv("MQTT_USERNAME", os.getenv("MQTT_USER", "")),
                password=os.getenv("MQTT_PASSWORD", os.getenv("MQTT_PASS", "")),
                client_id=os.getenv("MQTT_SNAPSHOT_CLIENT_ID", edge + "-snapshot-v2"),
                command_topic=topics[0], result_topic=topics[1], telemetry_topic=topics[2])
