import os
from pathlib import Path
from dotenv import load_dotenv

# Base paths
BACKEND_DIR = Path(__file__).resolve().parent
ROOT_DIR = BACKEND_DIR.parent.parent

# Load .env if exists (support backend, webgis, or root folder)
for env_candidate in [BACKEND_DIR / ".env", BACKEND_DIR.parent / ".env", ROOT_DIR / ".env"]:
    if env_candidate.exists():
        load_dotenv(dotenv_path=env_candidate)
        break

# Server Port & Host
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8000"))

# MQTT Settings (HiveMQ Cloud or local broker)
MQTT_HOST = os.getenv("MQTT_HOST", "829e7cb26c594257a7470e5a5af58064.s1.eu.hivemq.cloud")
MQTT_PORT = int(os.getenv("MQTT_PORT", "8883"))
MQTT_USER = os.getenv("MQTT_USER", "admin")
MQTT_PASS = os.getenv("MQTT_PASS", "12345678")
MQTT_CLIENT_ID = os.getenv("WEBGIS_MQTT_CLIENT_ID", "webgis-backend-hub")

# Storage directory
DATA_DIR = BACKEND_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
SNAPSHOTS_DIR = DATA_DIR / "snapshots"
SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)

# Edge Authentication & Live Streaming Configuration
EDGE_TOKEN = os.getenv("EDGE_TOKEN", "dev-edge-token")
LIVE_MAX_VIEWERS_PER_NODE = int(os.getenv("LIVE_MAX_VIEWERS_PER_NODE", "3"))
LIVE_MAX_VIEWERS_TOTAL = int(os.getenv("LIVE_MAX_VIEWERS_TOTAL", "10"))
LIVE_REQUIRE_AUTH = os.getenv("LIVE_REQUIRE_AUTH", "false").lower() in ("true", "1", "yes")
LIVE_MAX_FRAME_BYTES = int(os.getenv("LIVE_MAX_FRAME_BYTES", str(500 * 1024)))

