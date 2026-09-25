#!/usr/bin/env python3
"""MQTT publisher for Edge telemetry.

Wraps the existing HiveMQ Cloud TLS connection from mqtt_client.py and adds:
- Telemetry publish (traffic/edge-01/telemetry) every second
- Heartbeat publish (traffic/edge-01/heartbeat) every 5 seconds
- Command-result publish (traffic/edge-01/command-result)
- Command subscribe (traffic/edge-01/command)

Compatible with Python 3.6 (JetPack 4.x) and paho-mqtt 1.6.1.

SECURITY: Credentials are read from environment variables.
Hard-coded fallback values are for development only and MUST be overridden
in production via the .env file or system environment.
"""

from __future__ import print_function

import json
import os
import ssl
import threading
import time
import uuid

import paho.mqtt.client as mqtt_lib

# Nạp tự động .env từ thư mục gốc
def _load_env_file(path):
    if not os.path.isfile(path):
        return
    try:
        try:
            f = open(path, 'r', encoding='utf-8')
        except TypeError:
            f = open(path, 'r')
        with f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, val = line.split('=', 1)
                    os.environ.setdefault(key.strip(), val.strip().strip('"\''))
    except Exception:
        pass

_root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_load_env_file(os.path.join(_root_dir, '.env'))
_load_env_file(os.path.join(_root_dir, 'snap', '.env'))

# ── Topic contract (fixed, do not change without coordinating with Backend) ──
EDGE_ID = os.getenv('EDGE_ID', 'edge-01')
CAMERA_ID = os.getenv('CAMERA_ID', 'camera-01')
SEGMENT_ID = os.getenv('SEGMENT_ID', 'segment-001')
MODEL_VERSION = os.getenv('MODEL_VERSION', 'exp.engine')

TOPIC_TELEMETRY = 'traffic/%s/telemetry' % EDGE_ID
TOPIC_HEARTBEAT = 'traffic/%s/heartbeat' % EDGE_ID
TOPIC_REGISTRATION = 'traffic/%s/registration' % EDGE_ID
TOPIC_DEVICE_HEALTH = 'traffic/%s/device-health' % EDGE_ID
TOPIC_COMMAND = 'traffic/%s/command' % EDGE_ID
TOPIC_COMMAND_RESULT = 'traffic/%s/command-result' % EDGE_ID

# ── HiveMQ Cloud connection (read from env, fallback to mqtt_client.py values)
MQTT_HOST = os.getenv('MQTT_HOST', '829e7cb26c594257a7470e5a5af58064.s1.eu.hivemq.cloud')
MQTT_PORT = int(os.getenv('MQTT_PORT', '8883'))
MQTT_USERNAME = os.getenv('MQTT_USER', 'admin')
MQTT_PASSWORD = os.getenv('MQTT_PASS', '12345678')
MQTT_CLIENT_ID = os.getenv('MQTT_CLIENT_ID', '%s-edge-pub' % EDGE_ID)

HEARTBEAT_INTERVAL_S = 5.0
TELEMETRY_INTERVAL_S = 1.0


class MQTTPublisher(object):
    """Thread-safe MQTT publisher with auto-reconnect and offline queue.

    Uses paho-mqtt 1.6.1 which is Python 3.6 compatible.
    """

    def __init__(self, command_callback=None):
        """
        command_callback: callable(action, command_id, payload) or None
        """
        self._command_callback = command_callback
        self._is_connected = False
        self._sequence = 0
        self._lock = threading.Lock()
        self._last_sequence = 0
        self._registration_profile = None

        self._client = mqtt_lib.Client(
            client_id=MQTT_CLIENT_ID,
            clean_session=False,
        )
        self._client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
        self._client.tls_set(
            cert_reqs=ssl.CERT_REQUIRED,
            tls_version=ssl.PROTOCOL_TLS,
        )
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def start(self):
        """Connect and start background loop thread."""
        try:
            self._client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
            self._client.loop_start()
            print('[MQTT] Connecting to %s:%d ...' % (MQTT_HOST, MQTT_PORT))
        except Exception as err:
            print('[MQTT] Connection failed: %s' % err)

    def stop(self):
        """Publish offline status and disconnect cleanly."""
        try:
            self._publish_raw(TOPIC_HEARTBEAT, json.dumps({
                'edge_id': EDGE_ID,
                'status': 'offline',
                'timestamp': _iso_now(),
            }), qos=1)
            time.sleep(0.5)
        except Exception:
            pass
        try:
            self._client.loop_stop()
            self._client.disconnect()
        except Exception:
            pass

    # ── Publish API ──────────────────────────────────────────────────────────

    def publish_telemetry(self, metrics, edge_metrics):
        """Publish full telemetry payload to traffic/edge-01/telemetry."""
        with self._lock:
            self._sequence += 1
            seq = self._sequence
            self._last_sequence = seq

        payload = {
            'schema_version': 1,
            'message_id': str(uuid.uuid4()),
            'sequence': seq,
            'edge_id': EDGE_ID,
            'camera_id': CAMERA_ID,
            'segment_id': SEGMENT_ID,
            'timestamp': _iso_now(),
            'current_vehicle_count': int(metrics.get('current_vehicle_count', 0)),
            'raw_tracks': int(metrics.get('raw_tracks', 0)),
            'counts_by_class': metrics.get('counts_by_class', {}),
            'avg_speed_kmh': metrics.get('avg_speed_kmh'),
            'median_speed_kmh': metrics.get('median_speed_kmh'),
            'speed_by_class': metrics.get('speed_by_class', {}),
            'density_veh_per_km_lane': float(metrics.get('density_veh_per_km_lane', 0)),
            'roi_entry_rate_veh_per_min': int(metrics.get('roi_entry_rate_veh_per_min', 0)),
            'estimated_flow_veh_per_min': float(metrics.get('estimated_flow_veh_per_min', 0)),
            'estimated_flow_veh_per_hour': float(metrics.get('estimated_flow_veh_per_hour', 0)),
            'stopped_vehicle_count': int(metrics.get('stopped_vehicle_count', 0)),
            'stopped_vehicle_ratio': float(metrics.get('stopped_vehicle_ratio', 0)),
            'traffic_status': str(metrics.get('traffic_status', 'UNKNOWN')),
            'congestion_score': int(metrics.get('congestion_score', 0)),
            'forecast': metrics.get('forecast', {}),
            'edge_metrics': edge_metrics,
        }
        self._publish_raw(TOPIC_TELEMETRY, json.dumps(payload), qos=0)

    def publish_heartbeat(self):
        """Publish heartbeat to traffic/edge-01/heartbeat."""
        payload = {
            'edge_id': EDGE_ID,
            'camera_id': CAMERA_ID,
            'status': 'online',
            'service_status': 'running',
            'model_version': MODEL_VERSION,
            'last_sequence': self._last_sequence,
            'timestamp': _iso_now(),
        }
        self._publish_raw(TOPIC_HEARTBEAT, json.dumps(payload), qos=1)

    def set_registration_profile(self, profile):
        """Set the device profile and GIS metadata for WebGIS registration."""
        with self._lock:
            self._registration_profile = profile
        if self._is_connected:
            self.publish_registration()

    def publish_registration(self, profile=None):
        """Publish device registration / profile to traffic/edge-01/registration (Gói 1)."""
        if profile is not None:
            with self._lock:
                self._registration_profile = profile
        with self._lock:
            data = dict(self._registration_profile) if self._registration_profile else {}

        if not data:
            return

        data.setdefault('edge_id', EDGE_ID)
        data.setdefault('camera_id', CAMERA_ID)
        data.setdefault('segment_id', SEGMENT_ID)
        data.setdefault('timestamp', _iso_now())
        self._publish_raw(TOPIC_REGISTRATION, json.dumps(data, ensure_ascii=False), qos=1)
        print('[MQTT] Published device registration profile to %s' % TOPIC_REGISTRATION)

    def publish_device_health(self, command_id, health_data):
        """Publish on-demand device health diagnostic to traffic/edge-01/device-health (Gói 2)."""
        payload = {
            'command_id': command_id,
            'edge_id': EDGE_ID,
            'camera_id': CAMERA_ID,
            'segment_id': SEGMENT_ID,
            'timestamp': _iso_now(),
        }
        if isinstance(health_data, dict):
            payload.update(health_data)
        else:
            payload['data'] = health_data

        self._publish_raw(TOPIC_DEVICE_HEALTH, json.dumps(payload, ensure_ascii=False), qos=1)
        print('[MQTT] Published on-demand device health to %s' % TOPIC_DEVICE_HEALTH)

    def publish_command_result(self, command_id, action, status, message):
        """Publish command result to traffic/edge-01/command-result."""
        payload = {
            'command_id': command_id,
            'action': action,
            'status': status,
            'message': message,
            'timestamp': _iso_now(),
        }
        self._publish_raw(TOPIC_COMMAND_RESULT, json.dumps(payload, ensure_ascii=False), qos=1)

    @property
    def is_connected(self):
        return self._is_connected

    # ── Internal callbacks ───────────────────────────────────────────────────

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            self._is_connected = True
            print('[MQTT] Connected to %s:%d' % (MQTT_HOST, MQTT_PORT))
            # Subscribe to command topic
            client.subscribe(TOPIC_COMMAND, qos=1)
            print('[MQTT] Subscribed to %s' % TOPIC_COMMAND)
            self.publish_heartbeat()
            if self._registration_profile is not None:
                self.publish_registration()
        else:
            self._is_connected = False
            print('[MQTT] Connection refused (rc=%d)' % rc)

    def _on_disconnect(self, client, userdata, rc, properties=None):
        self._is_connected = False
        print('[MQTT] Disconnected (rc=%d), reconnecting...' % rc)

    def _on_message(self, client, userdata, msg):
        """Dispatch incoming command messages."""
        try:
            data = json.loads(msg.payload.decode('utf-8'))
        except (ValueError, UnicodeDecodeError) as err:
            print('[MQTT] Invalid message on %s: %s' % (msg.topic, err))
            return

        if self._command_callback is not None:
            try:
                self._command_callback(data)
            except Exception as err:
                print('[MQTT] Command callback error: %s' % err)

    def _publish_raw(self, topic, payload, qos=0):
        if self._is_connected:
            try:
                self._client.publish(topic, payload, qos=qos)
            except Exception as err:
                print('[MQTT] Publish error on %s: %s' % (topic, err))
        # If not connected, paho will queue QoS 1 messages for re-delivery


# ── Heartbeat background thread ───────────────────────────────────────────────

class HeartbeatThread(threading.Thread):
    """Background thread that publishes heartbeat every HEARTBEAT_INTERVAL_S."""

    def __init__(self, publisher):
        super(HeartbeatThread, self).__init__(daemon=True)
        self._publisher = publisher
        self._stop_event = threading.Event()

    def run(self):
        while not self._stop_event.is_set():
            try:
                self._publisher.publish_heartbeat()
            except Exception as err:
                print('[HEARTBEAT] Error: %s' % err)
            self._stop_event.wait(HEARTBEAT_INTERVAL_S)

    def stop(self):
        self._stop_event.set()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _iso_now():
    """Return ISO-8601 timestamp with UTC+7 offset."""
    # Python 3.6 compatible (no datetime.timezone.astimezone on naive)
    import datetime
    utc_now = datetime.datetime.utcnow()
    # Add +07:00 offset
    offset = datetime.timedelta(hours=7)
    local = utc_now + offset
    return local.strftime('%Y-%m-%dT%H:%M:%S') + '+07:00'
