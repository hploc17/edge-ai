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
def _parse_port(val, default=8883):
    try:
        if isinstance(val, str):
            val = val.strip().strip("'\"").rstrip('\r\n')
            import re
            m = re.search(r'\d+', val)
            if m:
                return int(m.group(0))
        return int(val)
    except Exception:
        return default

MQTT_HOST = os.getenv('MQTT_HOST', '829e7cb26c594257a7470e5a5af58064.s1.eu.hivemq.cloud')
MQTT_PORT = _parse_port(os.getenv('MQTT_PORT', '8883'), 8883)
MQTT_USERNAME = os.getenv('MQTT_USER', 'admin')
MQTT_PASSWORD = os.getenv('MQTT_PASS', '12345678')
MQTT_AGENT_CLIENT_ID = os.getenv('MQTT_AGENT_CLIENT_ID', '%s-agent' % EDGE_ID)
MQTT_PIPELINE_CLIENT_ID = os.getenv('MQTT_PIPELINE_CLIENT_ID', '%s-pipeline' % EDGE_ID)
MQTT_CLIENT_ID = os.getenv('MQTT_CLIENT_ID', '%s-edge-pub' % EDGE_ID)

HEARTBEAT_INTERVAL_S = 5.0
TELEMETRY_INTERVAL_S = 1.0
DEFAULT_COMMAND_TTL = float(os.getenv('COMMAND_TTL_SECONDS', '30.0'))
ENABLE_EDGE_FORECAST = os.getenv('ENABLE_EDGE_FORECAST', '0').lower() in ('1', 'true', 'yes')


def parse_timestamp_seconds(value):
    """Parse ISO-8601 string or numeric timestamp to epoch seconds.
    Compatible with Python 3.6+ and Python 3.11+.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    val_str = str(value).strip()
    try:
        return float(val_str)
    except ValueError:
        pass
    import re
    import datetime
    if val_str.endswith('Z') or val_str.endswith('z'):
        val_str = val_str[:-1] + '+0000'
    val_str = re.sub(r'([+-]\d{2}):(\d{2})$', r'\1\2', val_str)
    for fmt in (
        '%Y-%m-%dT%H:%M:%S.%f%z',
        '%Y-%m-%dT%H:%M:%S%z',
        '%Y-%m-%dT%H:%M:%S.%f',
        '%Y-%m-%dT%H:%M:%S',
    ):
        try:
            dt = datetime.datetime.strptime(val_str, fmt)
            return dt.timestamp()
        except ValueError:
            pass
    return None


class MQTTPublisher(object):
    """Thread-safe MQTT publisher with auto-reconnect and offline queue.

    Uses paho-mqtt 1.6.1 which is Python 3.6 compatible.
    """

    def __init__(self, command_callback=None, client_id=None, is_agent=True):
        """
        command_callback: callable(action, command_id, payload) or None
        client_id: distinct fixed client ID (e.g. edge-01-agent or edge-01-pipeline)
        is_agent: True nếu là Jetson Agent (đại diện phần cứng Node, phát Heartbeat & LWT);
                  False nếu là Pipeline worker (chỉ phát Telemetry, KHÔNG đặt LWT lên Node heartbeat - Fix L4).
        """
        self._command_callback = command_callback
        self._is_connected = False
        self._sequence = 0
        self._lock = threading.Lock()
        self._last_sequence = 0
        self._registration_profile = None
        self._client_id = client_id or MQTT_CLIENT_ID
        self._is_agent = bool(is_agent)

        # Dynamic Edge ID & Topics (Hỗ trợ đổi ID tự động khi Web duyệt - Zero Touch)
        self._edge_id = os.getenv('EDGE_ID', EDGE_ID)
        self._topic_telemetry = 'traffic/%s/telemetry' % self._edge_id
        self._topic_heartbeat = 'traffic/%s/heartbeat' % self._edge_id
        self._topic_registration = 'traffic/%s/registration' % self._edge_id
        self._topic_device_health = 'traffic/%s/device-health' % self._edge_id
        self._topic_command = 'traffic/%s/command' % self._edge_id
        self._topic_command_result = 'traffic/%s/command-result' % self._edge_id

        self._client = mqtt_lib.Client(
            client_id=self._client_id,
            clean_session=True,
        )
        if MQTT_USERNAME:
            self._client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
        self._client.tls_set(
            cert_reqs=ssl.CERT_REQUIRED,
            tls_version=ssl.PROTOCOL_TLS,
        )
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

        # Cấu hình Last Will and Testament (LWT) (Fix L4):
        # CHỈ CÓ Agent mới được đặt LWT lên heartbeat của Node!
        # Pipeline worker TUYỆT ĐỐI không đặt LWT lên heartbeat để tránh làm sập trạng thái Node khi pipeline dừng/crash.
        if self._is_agent:
            will_payload = json.dumps({
                'edge_id': self._edge_id,
                'camera_id': CAMERA_ID,
                'status': 'offline',
                'timestamp': _iso_now(),
            })
            self._client.will_set(self._topic_heartbeat, payload=will_payload, qos=1, retain=True)

        # Telemetry worker queue (tránh spawn thread liên tục mỗi giây trong GStreamer probe)
        try:
            from queue import Queue, Empty
        except ImportError:
            from Queue import Queue, Empty
        self._telemetry_queue = Queue(maxsize=3)
        self._telemetry_worker_running = True
        self._telemetry_thread = threading.Thread(
            target=self._telemetry_worker_loop,
            name='MQTTTelemetryWorker'
        )
        self._telemetry_thread.daemon = True
        self._telemetry_thread.start()

        # Offline Queue cho các bản tin QoS >= 1 (kết quả lệnh, health) khi mất mạng (Fix L8)
        try:
            from collections import deque
        except ImportError:
            deque = list
        self._offline_queue = deque(maxlen=50)
        self._offline_queue_lock = threading.Lock()
        self._pipeline_status_callback = None

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def _telemetry_worker_loop(self):
        try:
            from queue import Empty
        except ImportError:
            from Queue import Empty
        while self._telemetry_worker_running:
            try:
                item = self._telemetry_queue.get(timeout=0.5)
                if item is None:
                    break
                metrics, edge_metrics = item
                self.publish_telemetry(metrics, edge_metrics)
                self._telemetry_queue.task_done()
            except Empty:
                continue
            except Exception as e:
                print('[MQTT] Telemetry worker error: %s' % e)

    def queue_telemetry(self, metrics, edge_metrics):
        """Đưa telemetry vào hàng đợi phát bất đồng bộ không block GStreamer probe."""
        try:
            if self._telemetry_queue.full():
                try:
                    self._telemetry_queue.get_nowait()
                except Exception:
                    pass
            self._telemetry_queue.put_nowait((metrics, edge_metrics))
        except Exception as e:
            print('[MQTT] Failed to queue telemetry: %s' % e)

    def start(self):
        """Connect and start background loop thread."""
        try:
            self._client.connect(MQTT_HOST, MQTT_PORT, keepalive=15)
            self._client.loop_start()
            print('[MQTT] Connecting to %s:%d (client_id=%s) ...' % (MQTT_HOST, MQTT_PORT, self._client_id))
        except Exception as err:
            print('[MQTT] Connection failed for %s: %s' % (self._client_id, err))

    def stop(self, publish_offline=False):
        """Publish offline status (optional) and disconnect cleanly."""
        self._telemetry_worker_running = False
        try:
            self._telemetry_queue.put_nowait(None)
        except Exception:
            pass
        if publish_offline and self._is_agent:
            try:
                self._publish_raw(TOPIC_HEARTBEAT, json.dumps({
                    'edge_id': self._edge_id,
                    'status': 'offline',
                    'timestamp': _iso_now(),
                }), qos=1, retain=True)
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
            'edge_id': self._edge_id,
            'camera_id': CAMERA_ID,
            'segment_id': SEGMENT_ID,
            'mac_address': self._get_cached_mac(),
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
            'edge_metrics': edge_metrics,
        }
        if ENABLE_EDGE_FORECAST and 'forecast' in metrics:
            payload['forecast'] = metrics['forecast']
        self._publish_raw(TOPIC_TELEMETRY, json.dumps(payload), qos=0)

    def _get_cached_mac(self):
        try:
            from communication.system_metrics import _get_mac_address
            return _get_mac_address()
        except Exception:
            try:
                from system_metrics import _get_mac_address
                return _get_mac_address()
            except Exception:
                return None

    def _get_cached_serial(self):
        try:
            from communication.system_metrics import _get_board_serial
            return _get_board_serial()
        except Exception:
            try:
                from system_metrics import _get_board_serial
                return _get_board_serial()
            except Exception:
                return None

    def set_pipeline_status_callback(self, callback):
        """Set callback function to query real-time pipeline running status."""
        self._pipeline_status_callback = callback

    def publish_heartbeat(self):
        """Publish heartbeat to traffic/{edge_id}/heartbeat (Liveness only, Fix L9: No redundant lat/lng)."""
        if not self._is_agent:
            return
        mac = self._get_cached_mac()
        serial = self._get_cached_serial()
        pipeline_running = False
        pipeline_pid = None
        if self._pipeline_status_callback:
            try:
                st = self._pipeline_status_callback()
                if isinstance(st, dict):
                    pipeline_running = bool(st.get('pipeline_running', False))
                    pipeline_pid = st.get('pid')
            except Exception:
                pass
        payload = {
            'edge_id': self._edge_id,
            'camera_id': CAMERA_ID,
            'status': 'online',
            'service_status': 'running',
            'pipeline_running': pipeline_running,
            'pipeline_pid': pipeline_pid,
            'model_version': MODEL_VERSION,
            'last_sequence': self._last_sequence,
            'mac_address': mac,
            'serial_number': serial,
            'timestamp': _iso_now(),
        }
        self._publish_raw(self._topic_heartbeat, json.dumps(payload), qos=1, retain=True)

    def set_registration_profile(self, profile):
        """Set the device profile and GIS metadata for WebGIS registration."""
        with self._lock:
            self._registration_profile = profile
        if self._is_connected and self._is_agent:
            self.publish_registration()

    def publish_registration(self, profile=None):
        """Publish device registration / profile to traffic/edge-01/registration (Gói 1)."""
        if not self._is_agent:
            return
        if profile is not None:
            with self._lock:
                self._registration_profile = profile
        with self._lock:
            data = dict(self._registration_profile) if self._registration_profile else {}

        if not data:
            return

        mac = self._get_cached_mac()
        data.setdefault('edge_id', EDGE_ID)
        data.setdefault('camera_id', CAMERA_ID)
        data.setdefault('segment_id', SEGMENT_ID)
        data.setdefault('timestamp', _iso_now())
        data['mac_address'] = mac
        data['serial_number'] = self._get_cached_serial()
        try:
            lat = os.getenv('NODE_LAT') or os.getenv('GEO_LAT')
            lng = os.getenv('NODE_LON') or os.getenv('GEO_LNG')
            if lat and lng:
                data.setdefault('latitude', float(lat))
                data.setdefault('longitude', float(lng))
        except Exception:
            pass
        self._publish_raw(TOPIC_REGISTRATION, json.dumps(data, ensure_ascii=False), qos=1)
        print('[MQTT] Published device registration profile to %s (MAC: %s)' % (TOPIC_REGISTRATION, mac))

    def publish_device_health(self, command_id, health_data):
        """Publish on-demand device health diagnostic to traffic/edge-01/device-health (Gói 2)."""
        payload = {
            'command_id': command_id,
            'edge_id': EDGE_ID,
            'camera_id': CAMERA_ID,
            'segment_id': SEGMENT_ID,
            'mac_address': self._get_cached_mac(),
            'timestamp': _iso_now(),
        }
        if isinstance(health_data, dict):
            payload.update(health_data)
        else:
            payload['data'] = health_data

        self._publish_raw(TOPIC_DEVICE_HEALTH, json.dumps(payload, ensure_ascii=False), qos=1)
        print('[MQTT] Published on-demand device health to %s' % TOPIC_DEVICE_HEALTH)

    def publish_command_result(self, command_id, action, status, message):
        """Publish command result to single logic topic traffic/{EDGE_ID}/command-result (Fix L1)."""
        mac = self._get_cached_mac()
        payload = {
            'command_id': command_id,
            'action': action,
            'status': status,
            'message': message,
            'edge_id': self._edge_id,
            'mac_address': mac,
            'serial_number': self._get_cached_serial(),
            'timestamp': _iso_now(),
        }
        raw_payload = json.dumps(payload, ensure_ascii=False)
        self._publish_raw(self._topic_command_result, raw_payload, qos=1)

    def update_edge_id(self, new_edge_id):
        """Dynamically adopt new EDGE_ID assigned by WebGIS, update .env and re-route MQTT topics."""
        if not new_edge_id or new_edge_id == self._edge_id:
            return

        old_edge_id = self._edge_id
        old_cmd_topic = self._topic_command

        print('[ZTP] Adopting new EDGE_ID: %s (previous: %s)' % (new_edge_id, old_edge_id))
        self._edge_id = new_edge_id
        self._topic_telemetry = 'traffic/%s/telemetry' % new_edge_id
        self._topic_heartbeat = 'traffic/%s/heartbeat' % new_edge_id
        self._topic_registration = 'traffic/%s/registration' % new_edge_id
        self._topic_device_health = 'traffic/%s/device-health' % new_edge_id
        self._topic_command = 'traffic/%s/command' % new_edge_id
        self._topic_command_result = 'traffic/%s/command-result' % new_edge_id

        # Update environment variable in-memory
        os.environ['EDGE_ID'] = new_edge_id

        # Persist new EDGE_ID to root .env file on disk
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env_path = os.path.join(root_dir, '.env')
        if os.path.isfile(env_path):
            try:
                with open(env_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                found = False
                new_lines = []
                for line in lines:
                    if line.strip().startswith('EDGE_ID='):
                        new_lines.append('EDGE_ID=%s\n' % new_edge_id)
                        found = True
                    else:
                        new_lines.append(line)
                if not found:
                    new_lines.append('EDGE_ID=%s\n' % new_edge_id)
                with open(env_path, 'w', encoding='utf-8') as f:
                    f.writelines(new_lines)
                print('[ZTP] Successfully persisted EDGE_ID=%s to %s' % (new_edge_id, env_path))
            except Exception as err:
                print('[ZTP] Warning: Failed to update .env: %s' % err)

        # Switch MQTT command topic subscription
        if self._is_connected and self._client:
            try:
                self._client.unsubscribe(old_cmd_topic)
                self._client.subscribe(self._topic_command, qos=1)
                print('[ZTP] Resubscribed command topic to: %s' % self._topic_command)
                self.publish_heartbeat()
            except Exception as err:
                print('[ZTP] Error resubscribing topic: %s' % err)

    @property
    def is_connected(self):
        return self._is_connected

    @property
    def offline_queue_size(self):
        with self._offline_queue_lock:
            return len(self._offline_queue)

    def _enqueue_offline(self, topic, payload, qos=1, retain=False):
        with self._offline_queue_lock:
            self._offline_queue.append((topic, payload, qos, retain))
            qsize = len(self._offline_queue)
        print('[MQTT] Offline: queued QoS %d message for %s (queue size: %d)' % (qos, topic, qsize))

    def _flush_offline_queue(self):
        """Flush queued QoS >= 1 messages upon successful reconnection (Fix L8)."""
        with self._offline_queue_lock:
            if not self._offline_queue:
                return
            messages = list(self._offline_queue)
            self._offline_queue.clear()

        print('[MQTT] Flushing %d offline QoS >= 1 messages upon reconnect...' % len(messages))
        failed = []
        for idx, item in enumerate(messages):
            topic, payload, qos, retain = item
            try:
                if retain:
                    try:
                        res = self._client.publish(topic, payload, qos=qos, retain=retain)
                    except TypeError:
                        res = self._client.publish(topic, payload, qos=qos)
                else:
                    res = self._client.publish(topic, payload, qos=qos)
                if getattr(res, 'rc', mqtt_lib.MQTT_ERR_SUCCESS) != mqtt_lib.MQTT_ERR_SUCCESS:
                    failed = messages[idx:]
                    break
            except Exception as err:
                print('[MQTT] Error flushing message to %s: %s' % (topic, err))
                failed = messages[idx:]
                break

        if failed:
            with self._offline_queue_lock:
                for item in reversed(failed):
                    self._offline_queue.appendleft(item)
            print('[MQTT] Re-queued %d messages due to flush failure' % len(failed))

    # ── Internal callbacks ───────────────────────────────────────────────────

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            self._is_connected = True
            print('[MQTT] Connected to %s:%d (client_id=%s, is_agent=%s)' % (MQTT_HOST, MQTT_PORT, self._client_id, self._is_agent))
            # Xả hàng đợi kết quả lệnh tồn đọng khi mất mạng trước đó (Fix L8)
            self._flush_offline_queue()
            if self._is_agent:
                # 1. Subscribe to single logic command topic: traffic/{EDGE_ID}/command (Fix L1)
                client.subscribe(self._topic_command, qos=1)
                print('[MQTT] [%s] Subscribed to %s' % (self._client_id, self._topic_command))

                # 2. Subscribe to ZTP Provisioning topic (nhận lệnh cấp phát ID tự động từ WebGIS)
                mac = self._get_cached_mac()
                if mac:
                    clean_mac = str(mac).replace(':', '').replace('-', '').strip().lower()
                    if clean_mac and clean_mac != '000000000000':
                        self._provisioning_topic = 'traffic/provisioning/%s' % clean_mac
                        client.subscribe(self._provisioning_topic, qos=1)
                        print('[MQTT] [%s] Subscribed to Provisioning topic: %s' % (self._client_id, self._provisioning_topic))

                self.publish_heartbeat()
                if self._registration_profile is not None:
                    self.publish_registration()
        else:
            self._is_connected = False
            print('[MQTT] Connection refused for %s (rc=%d)' % (self._client_id, rc))

    def _on_disconnect(self, client, userdata, rc, properties=None):
        self._is_connected = False
        print('[MQTT] Disconnected for %s (rc=%d), reconnecting...' % (self._client_id, rc))

    def _on_message(self, client, userdata, msg):
        """Dispatch incoming command messages and provisioning events."""
        try:
            data = json.loads(msg.payload.decode('utf-8'))
        except (ValueError, UnicodeDecodeError) as err:
            print('[MQTT] Invalid message on %s: %s' % (msg.topic, err))
            return

        # Kiểm tra nếu là bản tin cấp phát ID tự động từ Web (Zero-Touch Provisioning)
        if hasattr(self, '_provisioning_topic') and msg.topic == self._provisioning_topic:
            event = data.get('event') if isinstance(data, dict) else ''
            if event == 'node_approved':
                assigned_id = data.get('assigned_edge_id')
                if assigned_id:
                    print('[ZTP] Received node_approved with assigned_edge_id: %s' % assigned_id)
                    self.update_edge_id(assigned_id)
            return

        if self._command_callback is not None:
            cmd_action = data.get('action') if isinstance(data, dict) else 'unknown'
            cmd_id = data.get('command_id', '') if isinstance(data, dict) else ''
            cmd_ts = data.get('timestamp') if isinstance(data, dict) else None
            ttl = float(data.get('ttl', DEFAULT_COMMAND_TTL)) if isinstance(data, dict) else DEFAULT_COMMAND_TTL

            # L8: Kiểm tra TTL - từ chối các lệnh quá hạn do broker giữ hoặc mạng trễ
            if cmd_ts is not None:
                ts_sec = parse_timestamp_seconds(cmd_ts)
                if ts_sec is not None:
                    age = time.time() - ts_sec
                    if age > ttl:
                        print('[MQTT] Command %s (id=%s) expired: age=%.1fs > ttl=%.1fs' %
                              (cmd_action, cmd_id, age, ttl))
                        self.publish_command_result(
                            command_id=cmd_id,
                            action=cmd_action,
                            status='expired',
                            message='Command expired (age=%.1fs > ttl=%.1fs)' % (age, ttl),
                        )
                        return

            print('[MQTT] Received command: %s (id=%s)' % (cmd_action, cmd_id))
            try:
                self._command_callback(data)
            except Exception as err:
                print('[MQTT] Command callback error: %s' % err)

    def _publish_raw(self, topic, payload, qos=0, retain=False):
        """Publish payload to MQTT topic.

        Fix L8:
        - Nếu đang online: publish trực tiếp. Nếu có lỗi publish và qos >= 1, xếp hàng vào _offline_queue.
        - Nếu đang offline:
          * qos == 0 (telemetry realtime streaming): drop để tránh gửi số liệu cũ.
          * qos >= 1 (command results, health, critical): xếp hàng vào _offline_queue (tối đa 50)
            để xả tự động khi kết nối lại, đảm bảo kết quả lệnh không bị mất khi mất mạng.
        """
        if self._is_connected:
            try:
                if retain:
                    try:
                        res = self._client.publish(topic, payload, qos=qos, retain=retain)
                    except TypeError:
                        res = self._client.publish(topic, payload, qos=qos)
                else:
                    res = self._client.publish(topic, payload, qos=qos)
                if getattr(res, 'rc', mqtt_lib.MQTT_ERR_SUCCESS) != mqtt_lib.MQTT_ERR_SUCCESS and qos >= 1:
                    if topic != self._topic_heartbeat:
                        self._enqueue_offline(topic, payload, qos=qos, retain=retain)
            except Exception as err:
                print('[MQTT] Publish error on %s: %s' % (topic, err))
                if qos >= 1 and topic != self._topic_heartbeat:
                    self._enqueue_offline(topic, payload, qos=qos, retain=retain)
        else:
            if qos >= 1 and topic != self._topic_heartbeat:
                self._enqueue_offline(topic, payload, qos=qos, retain=retain)



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
                if getattr(self._publisher, '_is_agent', True):
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
