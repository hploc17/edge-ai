"""Dual-source snapshot service. No JPEG/disk/HTTP work in a DeepStream probe."""
from __future__ import print_function
import collections
import copy
import datetime
import hashlib
import json
import logging
import math
import os
import queue
import re
import threading
import time
import uuid
from urllib.parse import urlparse

try:
    from .config import source_mode
    from .outbox import Outbox
    from .sources import CsiCapture, encode_frame, label_demo_image, validate_jpeg
except ImportError:  # Also usable as a same-directory module by the existing main.
    from config import source_mode
    from outbox import Outbox
    from sources import CsiCapture, encode_frame, label_demo_image, validate_jpeg

LOG = logging.getLogger("jetson_snapshot")
ACTION = "capture_test_snapshot"
STATES = ("UNKNOWN", "FREE", "SLOW", "CONGESTED")
METRICS = ("current_vehicle_count", "avg_speed_kmh", "density_veh_per_km_lane",
           "estimated_flow_veh_per_min", "stopped_vehicle_ratio", "congestion_score")
ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def iso_timestamp(timestamp=None):
    return datetime.datetime.fromtimestamp(time.time() if timestamp is None else timestamp,
                                           datetime.timezone.utc).isoformat()


def timestamp_seconds(value):
    # strptime supports Python 3.6; datetime.fromisoformat does not.
    value = str(value)
    if value.endswith("Z"):
        value = value[:-1] + "+0000"
    value = re.sub(r"([+-]\d{2}):(\d{2})$", r"\1\2", value)
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.datetime.strptime(value, fmt).timestamp()
        except ValueError:
            pass
    raise ValueError("Expected timezone-aware ISO timestamp")


class SnapshotCoordinator(object):
    def __init__(self, api_url, edge_token, edge_id="edge-01", camera_id="camera-01",
                 segment_id="segment-001", congestion_confirm_seconds=15,
                 snapshot_cooldown_seconds=60, jpeg_quality=75, queue_size=2,
                 outbox_dir="./snapshot_outbox", outbox_max_items=500,
                 outbox_max_bytes=2 * 1024 * 1024 * 1024, upload_timeout_seconds=15,
                 encoder=None, uploader=None, result_callback=None, time_fn=None,
                 analysis_source=None, csi_capture=None, demo_labeler=None,
                 telemetry_stale_seconds=5, command_max_age_seconds=60,
                 frame_wait_seconds=12, retry_seconds=15, max_jpeg_bytes=2097152,
                 max_frame_bytes=33554432, wall_fn=None):
        parsed = urlparse(api_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username:
            raise ValueError("api_url must be http(s)://host[:port]")
        if not edge_token:
            raise ValueError("EDGE_TOKEN is required")
        if not 1 <= int(jpeg_quality) <= 100 or not 1 <= int(queue_size) <= 8:
            raise ValueError("JPEG quality 1..100; queue size 1..8")
        for v in (congestion_confirm_seconds, snapshot_cooldown_seconds, upload_timeout_seconds,
                  telemetry_stale_seconds, command_max_age_seconds, frame_wait_seconds, retry_seconds,
                  max_jpeg_bytes, max_frame_bytes, outbox_max_items):
            if not math.isfinite(float(v)) or float(v) <= 0:
                raise ValueError("Limits/timeouts must be finite and positive")
        if outbox_max_bytes < max_jpeg_bytes:
            raise ValueError("Outbox budget must fit at least one maximum-size JPEG")
        self.api_url, self.edge_token = api_url.rstrip("/"), edge_token
        self.edge_id, self.camera_id, self.segment_id = edge_id, camera_id, segment_id
        self.mode = source_mode(analysis_source or os.getenv("ANALYTICS_SOURCE", "csi"))
        self.confirm, self.cooldown, self.quality = float(congestion_confirm_seconds), float(snapshot_cooldown_seconds), int(jpeg_quality)
        self.stale, self.command_age = float(telemetry_stale_seconds), float(command_max_age_seconds)
        self.frame_wait, self.retry = float(frame_wait_seconds), float(retry_seconds)
        self.upload_timeout = float(upload_timeout_seconds)
        self.max_jpeg, self.max_frame = int(max_jpeg_bytes), int(max_frame_bytes)
        self.outbox_dir = os.path.abspath(outbox_dir)
        self._store_options = (self.outbox_dir, outbox_max_items, outbox_max_bytes, self.max_jpeg)
        self._time, self._wall = time_fn or time.monotonic, wall_fn or time.time
        self._encoder = encoder
        self._uploader = uploader or self._upload_http
        self._label = demo_labeler or label_demo_image
        self._capture = csi_capture or CsiCapture(
            sensor_id=int(os.getenv("CSI_SENSOR_ID", "0")), width=int(os.getenv("CSI_WIDTH", "1920")),
            height=int(os.getenv("CSI_HEIGHT", "1080")), fps=int(os.getenv("CSI_FPS", "30")),
            timeout=float(os.getenv("CSI_CAPTURE_TIMEOUT_SECONDS", "12")), max_bytes=self.max_jpeg)
        self._callback = result_callback or (lambda result: None)
        self._lock = threading.RLock()
        self._jobs = queue.Queue(maxsize=int(queue_size))
        self._waiting = collections.deque()
        self._active = set()
        self._results = collections.OrderedDict()
        self._limit = int(queue_size)
        self._telemetry = {"traffic_status": "UNKNOWN"}
        self._received = None
        self._network_timestamp = None
        self._since = None
        self._since_wall = None
        self._last_auto = None
        self._auto_inflight = False
        self._stop = threading.Event()
        self._worker = None
        self._session = None
        self._lease = None
        self._store = None

    def start(self):
        if self._worker and self._worker.is_alive():
            return
        import fcntl
        os.makedirs(self.outbox_dir, exist_ok=True)
        self._lease = open(os.path.join(self.outbox_dir, "worker.lock"), "a")
        try:
            fcntl.flock(self._lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._lease.close()
            self._lease = None
            raise RuntimeError("Another snapshot service owns this outbox; run ONE service per camera")
        self._stop.clear()
        self._worker = threading.Thread(target=self._worker_loop, name="snapshot-worker")
        self._worker.daemon = True
        self._worker.start()

    def stop(self, timeout=None):
        self._stop.set()
        if self._worker:
            self._worker.join(timeout)
            if self._worker.is_alive():
                return False  # Never close resources still owned by the worker.
        return True

    def _emit(self, command_id, status, message, **extra):
        if not command_id:
            return
        result = dict(command_id=command_id, action=ACTION, status=status,
                      message=message, timestamp=iso_timestamp(self._wall()), **extra)
        with self._lock:
            previous = self._results.get(command_id)
            if previous and previous["status"] in ("completed", "failed") and status == "queued":
                return  # Fast worker completion must not be overwritten by a late queued event.
            self._results[command_id] = result
            if status in ("completed", "failed"):
                self._active.discard(command_id)
            while len(self._results) > 2000:
                self._results.popitem(last=False)
        try:
            self._callback(result)
        except Exception:
            LOG.warning("Command-result callback failed (snapshot record retained)")

    def request_manual_snapshot(self, command_id):
        if not isinstance(command_id, str) or not ID_PATTERN.fullmatch(command_id):
            return False
        with self._lock:
            if command_id in self._results or command_id in self._active:
                # MQTT completion is advisory: Backend snapshot upload is authoritative.
                return True
            if self._stop.is_set() or len(self._active) >= self._limit:
                rejected = True
            else:
                rejected = False
                self._active.add(command_id)
                self._waiting.append((command_id, self._time()))
        if rejected:
            self._emit(command_id, "failed", "SNAPSHOT_BUSY")
            return False
        self._emit(command_id, "queued", "Snapshot request queued")
        return True

    def handle_mqtt_command(self, payload, retained=False):
        if retained:
            return False
        try:
            if isinstance(payload, bytes):
                if len(payload) > 8192:
                    return False
                payload = payload.decode("utf-8")
            if isinstance(payload, str):
                if len(payload) > 8192:
                    return False
                payload = json.loads(payload)
            if not isinstance(payload, dict) or payload.get("action") != ACTION:
                return False
            if payload.get("edge_id", self.edge_id) != self.edge_id:
                return False
            if "timestamp" in payload:
                age = self._wall() - timestamp_seconds(payload["timestamp"])
                if age > self.command_age or age < -5:
                    return False
        except (ValueError, TypeError, UnicodeError):
            return False
        return self.request_manual_snapshot(payload.get("command_id"))

    def update_telemetry(self, telemetry, now=None, network=False):
        if not isinstance(telemetry, dict):
            return False
        if telemetry.get("edge_id", self.edge_id) != self.edge_id:
            return False
        status = str(telemetry.get("traffic_status", "UNKNOWN")).upper()
        if status not in STATES:
            return False
        cleaned = {"traffic_status": status}
        for key in METRICS:
            value = telemetry.get(key)
            if value is not None:
                if isinstance(value, bool):
                    return False
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    return False
                if not math.isfinite(value) or value < 0:
                    return False
                cleaned[key] = value
        current = self._time() if now is None else float(now)
        with self._lock:
            if network:
                try:
                    stamp = timestamp_seconds(telemetry["timestamp"])
                except (KeyError, ValueError, TypeError):
                    return False
                if not -5 <= self._wall() - stamp <= self.stale:
                    return False
                if self._network_timestamp is not None and stamp <= self._network_timestamp:
                    return False
                self._network_timestamp = stamp
            cleaned["timestamp"] = telemetry.get("timestamp", iso_timestamp(self._wall()))
            gap = self._received is None or current - self._received > self.stale or current < self._received
            if status != "CONGESTED" or gap:
                self._since = None
                self._since_wall = None
                self._last_auto = None
            if status == "CONGESTED" and self._since is None:
                self._since, self._since_wall = current, self._wall()
            self._received, self._telemetry = current, cleaned
        return True

    def update_traffic_state(self, traffic_status, now=None):
        # Compatibility with existing main's status-only API; submit_frame supplies metrics.
        return self.update_telemetry({"traffic_status": traffic_status}, now=now)

    def _auto_due(self, now):
        return (not self._auto_inflight and self._since is not None and
                self._telemetry["traffic_status"] == "CONGESTED" and
                self._received is not None and 0 <= now - self._received <= self.stale and
                now - self._since >= self.confirm and
                (self._last_auto is None or now - self._last_auto >= self.cooldown))

    def should_map_frame(self, traffic_status=None, now=None):
        if self.mode != "csi" or self._stop.is_set():
            return False
        current = self._time() if now is None else float(now)
        with self._lock:
            if self._jobs.full():
                return False
            manual = bool(self._waiting and current - self._waiting[0][1] <= self.frame_wait)
            return manual or ((traffic_status is None or traffic_status == "CONGESTED") and self._auto_due(current))

    def submit_frame(self, frame_bgr, telemetry, now=None, color_format="BGR"):
        if self.mode != "csi" or frame_bgr is None or self._stop.is_set():
            return False  # A video frame is NEVER used as the snapshot in video mode.
        if color_format not in ("BGR", "RGBA") or getattr(frame_bgr, "nbytes", 0) > self.max_frame:
            return False
        current = self._time() if now is None else float(now)
        with self._lock:
            if not self.should_map_frame(telemetry.get("traffic_status"), now=current):
                return False
            owned_frame = frame_bgr.copy()  # Own memory before GstBuffer leaves the probe.
            return self._enqueue(current, frame=owned_frame, telemetry=copy.deepcopy(telemetry), color=color_format)

    def _enqueue(self, now, frame=None, telemetry=None, color="BGR"):
        # Caller holds _lock; bounded queue, no disk/network/encoding here.
        if self._jobs.full():
            return False
        requests = []
        if self._waiting and now - self._waiting[0][1] <= self.frame_wait:
            command, received = self._waiting.popleft()
            key = "manual-" + hashlib.sha256((self.edge_id + ":" + command).encode()).hexdigest()
            requests.append(dict(command_id=command, trigger_type="MANUAL", snapshot_id=key))
        if self._auto_due(now):
            key = "congestion-" + uuid.uuid4().hex
            requests.append(dict(trigger_type="CONGESTION", event_id=key, snapshot_id=key,
                                 started_at=iso_timestamp(self._since_wall)))
            self._last_auto, self._auto_inflight = now, True
        if not requests:
            return False
        latest = copy.deepcopy(telemetry if telemetry is not None else self._telemetry)
        if self.mode == "video" and (self._received is None or now - self._received > self.stale):
            latest = {"traffic_status": "UNKNOWN"}
        self._jobs.put_nowait(dict(requests=requests, frame=frame, color=color,
                                  telemetry=latest, captured_at=iso_timestamp(self._wall())))
        return True

    def _tick(self):
        expired = []
        with self._lock:
            now = self._time()
            while self._waiting and now - self._waiting[0][1] > self.frame_wait:
                expired.append(self._waiting.popleft()[0])
            if self.mode == "video" and not self._stop.is_set():
                self._enqueue(now)
        for command in expired:
            self._emit(command, "failed", "NO_FRESH_FRAME_OR_WORKER_BUSY")

    def _worker_loop(self):
        try:
            self._store = Outbox(*self._store_options)
            while not self._stop.is_set() or not self._jobs.empty():
                if not self._stop.is_set():
                    self._tick()
                try:
                    job = self._jobs.get(timeout=0.1)
                except queue.Empty:
                    key = self._store.ready()
                    if key and not self._stop.is_set():
                        self._try_upload(key)
                    continue
                try:
                    for request in job["requests"]:
                        self._process_request(job, request)
                finally:
                    with self._lock:
                        if any(r["trigger_type"] == "CONGESTION" for r in job["requests"]):
                            self._auto_inflight = False
                    self._jobs.task_done()
            with self._lock:
                abandoned = list(self._waiting)
                self._waiting.clear()
            for command, _ in abandoned:
                self._emit(command, "failed", "SNAPSHOT_SERVICE_STOPPED")
        except Exception:
            LOG.exception("Snapshot worker stopped; check local disk and configuration")
            self._stop.set()
        finally:
            if self._store:
                self._store.close()
            if self._session:
                self._session.close()
            if self._lease:
                self._lease.close()
                self._lease = None

    def _payload(self, job, request):
        payload = dict(request)
        telemetry = job["telemetry"]
        payload.update(edge_id=self.edge_id, camera_id=self.camera_id, segment_id=self.segment_id,
                       timestamp=job["captured_at"], traffic_status=telemetry.get("traffic_status", "UNKNOWN"),
                       analysis_source="VIDEO_DEMO" if self.mode == "video" else "CSI",
                       snapshot_source="CSI_DIRECT" if self.mode == "video" else "PIPELINE_FRAME",
                       source_mismatch="true" if self.mode == "video" else "false")
        for key in METRICS:
            value = telemetry.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                payload[key] = value
        if self.mode == "video":
            payload["metadata"] = json.dumps({"note": "Metrics/trigger refer to DEMO VIDEO, not this CSI image",
                                               "analysis_timestamp": telemetry.get("timestamp")})
        return payload

    def _process_request(self, job, request):
        key, command = request["snapshot_id"], request.get("command_id")
        existing = self._store.get(key)
        if existing:
            if existing["state"] == "captured":
                self._try_upload(key)
            elif existing["result"]:
                result = existing["result"]
                extras = {k: result[k] for k in ("snapshot_url", "snapshot_id") if k in result}
                self._emit(command, result["status"], result.get("message", "Previous result"), **extras)
            return
        if not self._store.has_capacity():
            self._emit(command, "failed", "OUTBOX_FULL_NO_UNSENT_IMAGE_DELETED")
            LOG.warning("Outbox full: refusing new capture, preserving unsent images")
            return
        payload = self._payload(job, request)
        self._store.reserve(payload)
        try:
            if self.mode == "video":
                raw = self._capture(self.quality)
                payload["timestamp"] = iso_timestamp(self._wall())
                jpeg = self._label(raw, self.quality, payload["timestamp"], request["trigger_type"])
            else:
                jpeg = (self._encoder(job["frame"], self.quality) if self._encoder else
                        encode_frame(job["frame"], self.quality, job["color"]))
            validate_jpeg(jpeg, self.max_jpeg)
            self._store.save(key, jpeg, payload)
        except Exception as error:
            # Don't expose HTTP tokens, URLs or arbitrary exceptions to MQTT.
            code = "SNAPSHOT_CAPTURE_OR_ENCODE_FAILED"
            LOG.exception(
    		"%s: %s (%s)",
    		code,
    		str(error),
    		type(error).__name__
		)
            if os.path.isfile(self._store.path(key)):
                # Disk/ledger failure AFTER atomic JPEG rename: preserve for recovery, not prune.
                self._store.mark_captured(key)
                self._store.defer(key, self.retry)
                self._emit(command, "queued", "JPEG_SAVED_WAITING_FOR_BACKEND")
                return
            self._store.finish(key, "failed", dict(status="failed", message=code))
            self._emit(command, "failed", code)
            return
        self._try_upload(key)

    def _try_upload(self, key):
        row = self._store.get(key)
        payload, command = row["payload"], row["payload"].get("command_id")
        try:
            with open(self._store.path(key), "rb") as stream:
                jpeg = validate_jpeg(stream.read(self.max_jpeg + 1), self.max_jpeg)
            result = self._uploader(payload, jpeg)
            url = result.get("snapshot_url", "") if isinstance(result, dict) else ""
            expected = "/api/v1/snapshots/" + key + "/image"
            if not isinstance(result, dict) or result.get("success") is not True or url != expected:
                raise ValueError("Unconfirmed upload response")
        except Exception as error:
            self._store.defer(key, self.retry)
            self._emit(command, "queued", "JPEG_SAVED_WAITING_FOR_BACKEND")
            LOG.warning("Upload pending (%s); JPEG retained", type(error).__name__)
            return False
        completed = dict(status="completed", message="Snapshot uploaded", snapshot_id=key, snapshot_url=url)
        self._store.finish(key, "complete", completed)
        # Only acknowledged JPEGs are removed. Keep receipt for restart idempotency.
        self._store.remove_image(key)
        self._store.prune()
        self._emit(command, "completed", completed["message"], snapshot_id=key, snapshot_url=url)
        return True

    def _upload_http(self, payload, jpeg):
        try:
            import requests
            if self._session is None:
                self._session = requests.Session()
            response = self._session.post(self.api_url + "/api/v1/snapshots",
                                          headers={"Authorization": "Bearer " + self.edge_token},
                                          files={"image": ("snapshot.jpg", jpeg, "image/jpeg")}, data=payload,
                                          timeout=(3, self.upload_timeout), allow_redirects=False)
            try:
                if not 200 <= response.status_code < 300:
                    raise RuntimeError("HTTP_UPLOAD_REJECTED_%d" % response.status_code)
                return response.json()
            finally:
                response.close()
        except ImportError:
            # Fallback to standard library urllib.request when requests is not installed
            try:
                import urllib.request as urllib_req
            except ImportError:
                import urllib2 as urllib_req
            boundary = 'Boundary-%s' % uuid.uuid4().hex
            body_parts = []
            for k, v in payload.items():
                body_parts.append(
                    ('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n' % (boundary, k, v)).encode('utf-8')
                )
            body_parts.append(
                ('--%s\r\nContent-Disposition: form-data; name="image"; filename="snapshot.jpg"\r\nContent-Type: image/jpeg\r\n\r\n' % boundary).encode('utf-8')
            )
            body_parts.append(jpeg if isinstance(jpeg, (bytes, bytearray)) else bytes(jpeg))
            body_parts.append(('\r\n--%s--\r\n' % boundary).encode('utf-8'))
            body = b''.join(body_parts)

            req = urllib_req.Request(
                self.api_url + "/api/v1/snapshots",
                data=body,
                headers={
                    'Content-Type': 'multipart/form-data; boundary=%s' % boundary,
                    'Authorization': 'Bearer ' + self.edge_token,
                }
            )
            with urllib_req.urlopen(req, timeout=self.upload_timeout) as resp:
                status_code = resp.getcode()
                if not 200 <= status_code < 300:
                    raise RuntimeError("HTTP_UPLOAD_REJECTED_%d" % status_code)
                return json.loads(resp.read().decode('utf-8'))

    def pending_jobs(self):
        return self._jobs.qsize()

    def is_running(self):
        return bool(self._worker and self._worker.is_alive() and not self._stop.is_set())
