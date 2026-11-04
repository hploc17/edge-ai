#!/usr/bin/env python3
"""Central settings and environment variables management.

Compatible with Python 3.6 (JetPack 4.x).
Reads from environment variables with production-ready defaults.
"""

import os
from pathlib import Path

# Base Paths
BASE_DIR = Path(__file__).resolve().parent.parent
CONFIGS_DIR = BASE_DIR / "configs"

# Nạp duy nhất từ file .env tại thư mục gốc của project
_env_path = BASE_DIR / ".env"
if _env_path.is_file():
    try:
        with open(str(_env_path), "r", encoding="utf-8") as _f:
            for _l in _f:
                _l = _l.strip()
                if _l and not _l.startswith("#") and "=" in _l:
                    _k, _v = _l.split("=", 1)
                    os.environ.setdefault(_k.strip(), _v.strip().strip("\"'"))
    except Exception:
        pass

OUTBOX_DIR = Path(os.getenv("OUTBOX_DIR", str(BASE_DIR / "outbox")))

# Backend REST API
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")
EDGE_TOKEN = os.getenv("EDGE_TOKEN", "dev-edge-token")
UPLOAD_ENDPOINT = BACKEND_URL + "/api/v1/congestion-events/snapshot"

# Edge Device Identification & WebGIS Metadata
EDGE_ID = os.getenv("EDGE_ID", "edge-01")
DEVICE_NAME = os.getenv("DEVICE_NAME", "Nút giao Nguyễn Trãi - Khuất Duy Tiến")
CAMERA_ID = os.getenv("CAMERA_ID", "camera-01")
SEGMENT_ID = os.getenv("SEGMENT_ID", "segment-001")
ROAD_NAME = os.getenv("ROAD_NAME", "Lê Đức Thọ")
SENSOR_ID = int(os.getenv("SENSOR_ID", "0"))

# Geospatial Coordinates (WGS84) & Camera Orientation (Fix L9: NODE_* standard with GEO_* fallback)
NODE_LAT = float(os.getenv("NODE_LAT", os.getenv("GEO_LAT", "10.852708")))
NODE_LON = float(os.getenv("NODE_LON", os.getenv("GEO_LNG", "106.660508")))
NODE_ALTITUDE_M = float(os.getenv("NODE_ALTITUDE_M", os.getenv("GEO_ALTITUDE_M", "12.0")))
GEO_LAT = NODE_LAT
GEO_LNG = NODE_LON
GEO_ALTITUDE_M = NODE_ALTITUDE_M
CAMERA_HEADING = float(os.getenv("CAMERA_HEADING", "45.0"))
CAMERA_FOV = float(os.getenv("CAMERA_FOV", "65.0"))

# MQTT Configuration
_raw_mqtt_host = os.getenv("MQTT_HOST", "829e7cb26c594257a7470e5a5af58064.s1.eu.hivemq.cloud")
for _scheme in ("mqtts://", "mqtt://", "ssl://", "tcp://"):
    if _raw_mqtt_host.startswith(_scheme):
        _raw_mqtt_host = _raw_mqtt_host[len(_scheme):]
        break
if ":" in _raw_mqtt_host:
    _raw_mqtt_host, _port = _raw_mqtt_host.rsplit(":", 1)
    MQTT_PORT = int(_port)
else:
    MQTT_PORT = int(os.getenv("MQTT_PORT", "8883"))
MQTT_HOST = _raw_mqtt_host

MQTT_USER = os.getenv("MQTT_USER", "admin")
MQTT_PASS = os.getenv("MQTT_PASS", "12345678")
MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", "{}-edge-pub".format(EDGE_ID))

# MQTT Topics
TOPIC_TELEMETRY = "traffic/{}/telemetry".format(EDGE_ID)
TOPIC_HEARTBEAT = "traffic/{}/heartbeat".format(EDGE_ID)
TOPIC_REGISTRATION = "traffic/{}/registration".format(EDGE_ID)
TOPIC_DEVICE_HEALTH = "traffic/{}/device-health".format(EDGE_ID)
TOPIC_COMMAND = "traffic/{}/command".format(EDGE_ID)
TOPIC_COMMAND_RESULT = "traffic/{}/command-result".format(EDGE_ID)

# Snapshot Guard Thresholds
CONGESTION_CONFIRM_SECONDS = float(os.getenv("CONGESTION_CONFIRM_SECONDS", "15.0"))
SNAPSHOT_COOLDOWN_SECONDS = float(os.getenv("SNAPSHOT_COOLDOWN_SECONDS", "60.0"))
JPEG_QUALITY = int(os.getenv("JPEG_QUALITY", "75"))

# AI Congestion Forecast (Tạm thời tắt trên Edge để tiết kiệm tài nguyên; quy hoạch thành Future Work tại Server)
ENABLE_EDGE_FORECAST = os.getenv("ENABLE_EDGE_FORECAST", "0").lower() in ("1", "true", "yes")

# Outbox Limits
OUTBOX_MAX_FILES = int(os.getenv("OUTBOX_MAX_FILES", "500"))
OUTBOX_MAX_SIZE_BYTES = int(os.getenv("OUTBOX_MAX_SIZE_BYTES", str(2 * 1024 * 1024 * 1024))) # 2GB
OUTBOX_RETRY_INTERVAL_S = float(os.getenv("OUTBOX_RETRY_INTERVAL_S", "30.0"))

# Resolution Standard
FRAME_WIDTH = 1280
FRAME_HEIGHT = 720

# On-Demand Live Streaming (Zero-Queue GStreamer Tee Branch)
LIVE_STREAM_ENABLED = os.getenv("LIVE_STREAM_ENABLED", "0").lower() in ("1", "true", "yes")
LIVE_WIDTH = int(os.getenv("LIVE_WIDTH", "640"))
LIVE_HEIGHT = int(os.getenv("LIVE_HEIGHT", "360"))
LIVE_FPS = int(os.getenv("LIVE_FPS", "10"))
LIVE_JPEG_QUALITY = int(os.getenv("LIVE_JPEG_QUALITY", "60"))

