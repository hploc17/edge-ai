#!/usr/bin/env python3
"""Central settings and environment variables management.

Compatible with Python 3.6 (JetPack 4.x).
Reads from a single centralized .env file with production-ready defaults.
"""

from __future__ import print_function
import os
from pathlib import Path

# Base Paths
BASE_DIR = Path(__file__).resolve().parent.parent
CONFIGS_DIR = BASE_DIR / "configs"

def load_unified_env(env_path=None):
    """Load variables from a single .env file into os.environ."""
    target = None
    if env_path and Path(env_path).is_file():
        target = Path(env_path)
    else:
        for cand in [BASE_DIR / ".env", Path("/app/.env"), Path("/workspace/.env"), Path(".env")]:
            if cand.is_file():
                target = cand.resolve()
                break
    if not target:
        return None

    try:
        with open(str(target), "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip("'\"")
                    # Gán vào os.environ (chỉ setdefault để không ghi đè cờ truyền tường minh qua CLI/Docker)
                    os.environ.setdefault(k, v)
        return str(target)
    except Exception as err:
        print("[WARN] Failed to load .env from %s: %s" % (target, err))
        return None

# Nạp .env ngay khi import
LOADED_ENV_PATH = load_unified_env()

# Thư mục Outbox
OUTBOX_DIR = Path(os.getenv("OUTBOX_DIR", str(BASE_DIR / "outbox")))

# Backend REST API
BACKEND_URL = os.getenv("BACKEND_URL", "http://192.168.1.14:8000").rstrip("/")
EDGE_TOKEN = os.getenv("EDGE_TOKEN", "dev-edge-token")
UPLOAD_ENDPOINT = BACKEND_URL + "/api/v1/snapshots/upload"

# Edge Hardware Identification
EDGE_ID = os.getenv("EDGE_ID", "edge-01")
CAMERA_ID = os.getenv("CAMERA_ID", "camera-01")
SEGMENT_ID = os.getenv("SEGMENT_ID", "segment-001")
SENSOR_ID = int(os.getenv("SENSOR_ID", "0"))

# GIS & Station Metadata (được WebGIS quản lý và cấu hình từ Web)
DEVICE_NAME = os.getenv("DEVICE_NAME") or "Thiết bị mới ({})".format(EDGE_ID)
ROAD_NAME = os.getenv("ROAD_NAME") or ""
GEO_LAT = float(os.getenv("GEO_LAT")) if os.getenv("GEO_LAT") else None
GEO_LNG = float(os.getenv("GEO_LNG")) if os.getenv("GEO_LNG") else None
GEO_ALTITUDE_M = float(os.getenv("GEO_ALTITUDE_M")) if os.getenv("GEO_ALTITUDE_M") else None
CAMERA_HEADING = float(os.getenv("CAMERA_HEADING")) if os.getenv("CAMERA_HEADING") else None
CAMERA_FOV = float(os.getenv("CAMERA_FOV")) if os.getenv("CAMERA_FOV") else None

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
MQTT_AGENT_CLIENT_ID = os.getenv("MQTT_AGENT_CLIENT_ID", "{}-agent".format(EDGE_ID))
MQTT_PIPELINE_CLIENT_ID = os.getenv("MQTT_PIPELINE_CLIENT_ID", "{}-pipeline".format(EDGE_ID))
MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", "{}-edge-pub".format(EDGE_ID))

# MQTT Topics
TOPIC_TELEMETRY = "traffic/{}/telemetry".format(EDGE_ID)
TOPIC_HEARTBEAT = "traffic/{}/heartbeat".format(EDGE_ID)
TOPIC_REGISTRATION = "traffic/{}/registration".format(EDGE_ID)
TOPIC_COMMAND = "traffic/{}/command".format(EDGE_ID)
TOPIC_COMMAND_RESULT = "traffic/{}/command-result".format(EDGE_ID)

# Snapshot Guard Thresholds
ENABLE_SNAPSHOT = os.getenv("ENABLE_SNAPSHOT", "true").lower() in ("true", "1", "yes")
CONGESTION_CONFIRM_SECONDS = float(os.getenv("CONGESTION_CONFIRM_SECONDS", "15.0"))
SNAPSHOT_COOLDOWN_SECONDS = float(os.getenv("SNAPSHOT_COOLDOWN_SECONDS", "60.0"))
JPEG_QUALITY = int(os.getenv("JPEG_QUALITY", "75"))

# Resolution Standard
FRAME_WIDTH = 1280
FRAME_HEIGHT = 720

# Video & Camera CSI Configuration
VIDEO_SOURCE = os.getenv("VIDEO_SOURCE", "csi")
CSI_FLIP_METHOD = int(os.getenv("CSI_FLIP_METHOD", "0"))
