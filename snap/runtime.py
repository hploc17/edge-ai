"""Configuration factory for embedding in your existing main (no new MQTT client)."""
import os
try:
    from .snapshot_service import SnapshotCoordinator
    from .config import load_env_file
except ImportError:
    from snapshot_service import SnapshotCoordinator
    from config import load_env_file


def _ensure_env():
    if "BACKEND_URL" not in os.environ:
        root_env = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))
        if os.path.isfile(root_env):
            load_env_file(root_env)
        else:
            snap_env = os.path.join(os.path.dirname(__file__), ".env")
            if os.path.isfile(snap_env):
                load_env_file(snap_env)


def create_from_env(result_callback=None, analysis_source=None):
    _ensure_env()
    return SnapshotCoordinator(
        api_url=os.getenv("BACKEND_URL", "http://localhost:8000"),
        edge_token=os.getenv("EDGE_TOKEN", "dev-edge-token"),
        edge_id=os.getenv("EDGE_ID", "edge-01"), camera_id=os.getenv("CAMERA_ID", "camera-01"),
        segment_id=os.getenv("SEGMENT_ID", "segment-001"),
        analysis_source=analysis_source or os.getenv("ANALYTICS_SOURCE", "csi"),
        congestion_confirm_seconds=float(os.getenv("CONGESTION_CONFIRM_SECONDS", "15")),
        snapshot_cooldown_seconds=float(os.getenv("SNAPSHOT_COOLDOWN_SECONDS", "60")),
        jpeg_quality=int(os.getenv("JPEG_QUALITY", "75")),
        queue_size=int(os.getenv("SNAPSHOT_QUEUE_SIZE", "2")),
        outbox_dir=os.getenv("SNAPSHOT_OUTBOX_DIR", "./snapshot_outbox"),
        outbox_max_items=int(os.getenv("SNAPSHOT_OUTBOX_MAX_ITEMS", "500")),
        outbox_max_bytes=int(os.getenv("SNAPSHOT_OUTBOX_MAX_BYTES", "2147483648")),
        max_jpeg_bytes=int(os.getenv("SNAPSHOT_MAX_JPEG_BYTES", "2097152")),
        telemetry_stale_seconds=float(os.getenv("TELEMETRY_STALE_SECONDS", "5")),
        upload_timeout_seconds=float(os.getenv("SNAPSHOT_UPLOAD_TIMEOUT_SECONDS", "15")),
        frame_wait_seconds=float(os.getenv("SNAPSHOT_FRAME_WAIT_SECONDS", "12")),
        retry_seconds=float(os.getenv("SNAPSHOT_RETRY_SECONDS", "15")),
        result_callback=result_callback)
