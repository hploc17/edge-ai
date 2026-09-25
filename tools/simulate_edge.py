#!/usr/bin/env python3
"""Jetson Nano Edge AI Simulator for Testing & Development.

Simulates:
1. Heartbeat publishing (every 5 seconds) to traffic/edge-01/heartbeat
2. Telemetry publishing (every 1 second) to traffic/edge-01/telemetry with live metrics
3. MQTT Command listener on traffic/edge-01/command:
   - capture_test_snapshot: Generates an annotated snapshot JPEG and uploads to backend
   - request_status: Responds with device status
   - reload_config: Simulates config reload
   - restart_analytics: Simulates pipeline restart
"""

import datetime
import json
import math
import os
import random
import ssl
import sys
import threading
import time
import uuid

try:
    import cv2
    import numpy as np
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("[ERROR] paho-mqtt is required. Run: pip install paho-mqtt")
    sys.exit(1)

try:
    import urllib.request as urllib_request
    import urllib.error as urllib_error
except ImportError:
    pass

# Configuration matching Backend
BACKEND_URL = os.getenv('BACKEND_URL', 'http://localhost:3000').rstrip('/')
EDGE_TOKEN = os.getenv('EDGE_TOKEN', 'CHANGE_ME_EDGE_TOKEN_RANDOM_STRING')
EDGE_ID = os.getenv('EDGE_ID', 'edge-01')
CAMERA_ID = os.getenv('CAMERA_ID', 'camera-01')
SEGMENT_ID = os.getenv('SEGMENT_ID', 'segment-001')

MQTT_HOST = os.getenv('MQTT_HOST', '829e7cb26c594257a7470e5a5af58064.s1.eu.hivemq.cloud')
MQTT_PORT = int(os.getenv('MQTT_PORT', '8883'))
MQTT_USER = os.getenv('MQTT_USER', 'admin')
MQTT_PASS = os.getenv('MQTT_PASS', '12345678')
MQTT_CLIENT_ID = os.getenv('MQTT_CLIENT_ID', 'jetson-nano-simulator-%s' % uuid.uuid4().hex[:6])

TOPIC_TELEMETRY = 'traffic/%s/telemetry' % EDGE_ID
TOPIC_HEARTBEAT = 'traffic/%s/heartbeat' % EDGE_ID
TOPIC_REGISTRATION = 'traffic/%s/registration' % EDGE_ID
TOPIC_DEVICE_HEALTH = 'traffic/%s/device-health' % EDGE_ID
TOPIC_COMMAND = 'traffic/%s/command' % EDGE_ID
TOPIC_COMMAND_RESULT = 'traffic/%s/command-result' % EDGE_ID

UPLOAD_ENDPOINT = BACKEND_URL + '/api/v1/congestion-events/snapshot'

def iso_now():
    now = datetime.datetime.utcnow() + datetime.timedelta(hours=7)
    return now.strftime('%Y-%m-%dT%H:%M:%S') + '+07:00'

def generate_test_frame(vehicle_count, avg_speed, status):
    """Generate a realistic test camera frame with road, ROI polygon and vehicle boxes."""
    width, height = 1280, 720
    frame = np.zeros((height, width, 3), dtype=np.uint8)

    # Road background
    cv2.rectangle(frame, (0, 0), (width, 240), (20, 25, 30), -1)  # Sky/Horizon
    pts_road = np.array([[380, 240], [900, 240], [1280, 720], [0, 720]], np.int32)
    cv2.fillPoly(frame, [pts_road], (45, 52, 58))  # Asphalt

    # Lane markings (dashed)
    for y in range(260, 720, 60):
        t1 = (y - 240) / 480.0
        x_left = int(480 - t1 * 300)
        x_mid = int(640)
        x_right = int(800 + t1 * 300)
        cv2.line(frame, (x_mid, y), (x_mid, min(y + 35, 719)), (220, 220, 220), int(2 + t1 * 4))

    # Yellow Analysis ROI polygon
    roi_pts = np.array([[320, 320], [960, 320], [1150, 680], [130, 680]], np.int32)
    cv2.polylines(frame, [roi_pts], isClosed=True, color=(0, 225, 255), thickness=3)
    cv2.putText(frame, "ANALYSIS ROI - CAMERA-01 (DUONG CONG HOA)", (330, 310),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 225, 255), 2)

    # Draw simulated vehicle bounding boxes
    classes = [('motorcycle', (0, 255, 128)), ('car', (255, 160, 50)), ('truck', (80, 80, 240))]
    rng = random.Random(int(time.time() // 3))
    for i in range(min(vehicle_count, 14)):
        c_name, color = rng.choice(classes)
        bx = rng.randint(220, 950)
        by = rng.randint(350, 600)
        bw = rng.randint(60, 150)
        bh = rng.randint(50, 100)
        tid = 100 + i * 7
        spd = max(3.0, round(avg_speed + rng.uniform(-4, 4), 1))

        cv2.rectangle(frame, (bx, by), (bx + bw, by + bh), color, 2)
        label = "#%d %s %.1f km/h" % (tid, c_name, spd)
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
        cv2.rectangle(frame, (bx, by - th - 8), (bx + tw + 6, by), color, -1)
        cv2.putText(frame, label, (bx + 3, by - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1)

    # Top overlay header
    cv2.rectangle(frame, (0, 0), (width, 50), (10, 15, 20), -1)
    status_color = (0, 200, 0) if status == 'FREE' else ((0, 200, 255) if status == 'SLOW' else (0, 0, 255))
    cv2.putText(frame, "JETSON NANO - DEEPSTREAM 6.0.1 AI LIVE PIPELINE", (20, 32),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    cv2.putText(frame, "STATUS: %s | VEHICLES: %d | SPEED: %.1f km/h" % (status, vehicle_count, avg_speed),
                (640, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.65, status_color, 2)

    # Timestamp
    cv2.putText(frame, iso_now(), (width - 260, height - 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 180), 1)

    success, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return buf.tobytes() if success else None

def upload_snapshot_to_backend(jpeg_bytes, event_id, metrics):
    """Upload JPEG bytes to Backend /api/v1/congestion-events/snapshot via multipart form."""
    try:
        boundary = 'Boundary-%s' % uuid.uuid4().hex
        body_parts = []

        fields = {
            'event_id': event_id,
            'edge_id': EDGE_ID,
            'camera_id': CAMERA_ID,
            'segment_id': SEGMENT_ID,
            'timestamp': iso_now(),
            'traffic_status': str(metrics.get('traffic_status', 'CONGESTED')),
            'current_vehicle_count': str(metrics.get('current_vehicle_count', 0)),
            'avg_speed_kmh': str(metrics.get('avg_speed_kmh', 12.5)),
            'density_veh_per_km_lane': str(metrics.get('density_veh_per_km_lane', 35.0)),
            'estimated_flow_veh_per_min': str(metrics.get('estimated_flow_veh_per_min', 24.0)),
            'stopped_vehicle_ratio': str(metrics.get('stopped_vehicle_ratio', 0.25)),
            'congestion_score': str(metrics.get('congestion_score', 45)),
        }

        for k, v in fields.items():
            body_parts.append(
                '--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n' % (boundary, k, v)
            )

        filename = 'camera-01_%s.jpg' % event_id[:8]
        body_parts.append(
            '--%s\r\nContent-Disposition: form-data; name="image"; filename="%s"\r\nContent-Type: image/jpeg\r\n\r\n'
            % (boundary, filename)
        )

        body = ''.join(body_parts).encode('utf-8') + jpeg_bytes + ('\r\n--%s--\r\n' % boundary).encode('utf-8')

        req = urllib_request.Request(
            UPLOAD_ENDPOINT,
            data=body,
            headers={
                'Content-Type': 'multipart/form-data; boundary=%s' % boundary,
                'Authorization': 'Bearer %s' % EDGE_TOKEN,
                'X-Event-Id': event_id,
            },
            method='POST',
        )
        with urllib_request.urlopen(req, timeout=10) as resp:
            print("[SNAPSHOT] Successfully uploaded snapshot to %s (HTTP %d)" % (UPLOAD_ENDPOINT, resp.getcode()))
            return True
    except Exception as err:
        print("[SNAPSHOT] Upload failed: %s" % err)
        return False

class JetsonSimulator:
    def __init__(self):
        self.client = mqtt.Client(client_id=MQTT_CLIENT_ID)
        self.client.username_pw_set(MQTT_USER, MQTT_PASS)
        self.client.tls_set(cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLSv1_2)

        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.sequence = 0
        self.running = True

        # State
        self.vehicle_count = 24
        self.avg_speed = 12.5
        self.status = 'SLOW'

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print("[MQTT] Connected to HiveMQ Broker: %s:%d" % (MQTT_HOST, MQTT_PORT))
            client.subscribe(TOPIC_COMMAND, qos=1)
            print("[MQTT] Subscribed to command topic: %s" % TOPIC_COMMAND)
            self.publish_heartbeat()
            self.publish_registration()
        else:
            print("[MQTT] Connection refused with code: %d" % rc)

    def publish_registration(self):
        profile = {
            'event': 'device_registered',
            'edge_id': EDGE_ID,
            'device_name': 'Nút giao Nguyễn Trãi - Khuất Duy Tiến (Simulator)',
            'timestamp': iso_now(),
            'geo': {
                'lat': 20.998412,
                'lng': 105.795123,
                'altitude_m': 12.5,
                'segment_id': SEGMENT_ID,
                'road_name': 'Nguyễn Trãi',
                'heading': 45.0,
                'fov': 65.0,
            },
            'spatial_config': {
                'road_length_m': 20.0,
                'road_width_m': 7.0,
                'lane_count': 2,
                'homography_calibrated': True,
            },
            'system_profile': {
                'hardware': 'NVIDIA Jetson Nano (Simulated)',
                'app_version': '1.0.0',
                'model_version': 'yolov11n_traffic.engine',
                'supported_classes': ['motorcycle', 'car', 'bus', 'truck'],
            },
            'supported_commands': [
                'get_health',
                'request_status',
                'reload_config',
                'restart_analytics',
                'capture_test_snapshot',
            ],
        }
        self.client.publish(TOPIC_REGISTRATION, json.dumps(profile, ensure_ascii=False), qos=1)
        print("[MQTT] Published device registration profile to %s" % TOPIC_REGISTRATION)

    def on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode('utf-8'))
            action = payload.get('action')
            command_id = payload.get('command_id', str(uuid.uuid4()))
            print("[CMD RECEIVED] Action: %s, ID: %s" % (action, command_id))

            if action == 'get_health':
                health = {
                    'command_id': command_id,
                    'edge_id': EDGE_ID,
                    'timestamp': iso_now(),
                    'general': {
                        'uptime_seconds': int(time.time() - self.start_time),
                        'service_status': 'running',
                    },
                    'network': {
                        'local_ip': '192.168.1.105',
                        'mac_address': '48:B0:2D:1A:2B:3C',
                        'status': 'connected',
                    },
                    'hardware': {
                        'cpu_usage_pct': random.randint(45, 65),
                        'cpu_cores': 4,
                        'ram_used_mb': 2450,
                        'ram_total_mb': 3964,
                        'ram_usage_pct': 61,
                        'swap_used_mb': 256,
                        'swap_total_mb': 2048,
                        'gpu_usage_pct': random.randint(70, 88),
                        'temperature_c': round(random.uniform(55.0, 64.0), 1),
                        'power_mode': '10W_MAXN',
                    },
                    'storage': {
                        'disk_total_gb': 29.5,
                        'disk_free_gb': 14.8,
                        'disk_usage_pct': 50,
                        'outbox_unsent_images': 0,
                    },
                    'pipeline': {
                        'camera_status': 'streaming',
                        'pipeline_fps': 28.5,
                        'inference_latency_ms': 35.1,
                    },
                }
                self.client.publish(TOPIC_DEVICE_HEALTH, json.dumps(health, ensure_ascii=False), qos=1)
                self.publish_result(command_id, action, 'completed', health)
                print("[CMD RESULT PUBLISHED] get_health -> %s" % TOPIC_DEVICE_HEALTH)

            elif action == 'capture_test_snapshot':
                print("[CMD] Handling capture_test_snapshot...")
                jpeg = generate_test_frame(self.vehicle_count, self.avg_speed, self.status)
                if jpeg:
                    event_id = str(uuid.uuid4())
                    metrics = {
                        'traffic_status': self.status,
                        'current_vehicle_count': self.vehicle_count,
                        'avg_speed_kmh': self.avg_speed,
                        'density_veh_per_km_lane': 38.5,
                        'estimated_flow_veh_per_min': 28.0,
                        'stopped_vehicle_ratio': 0.32,
                        'congestion_score': 55 if self.status == 'CONGESTED' else 35,
                    }
                    upload_snapshot_to_backend(jpeg, event_id, metrics)
                    self.publish_result(command_id, action, 'completed', 'Khung hinh tu camera Jetson da duoc chup va tai len.')
                else:
                    self.publish_result(command_id, action, 'error', 'Khong the ma hoa JPEG tu frame.')

            elif action == 'request_status':
                self.publish_result(command_id, action, 'completed', 'Jetson Nano: Pipeline dang chay binh thuong (28.4 FPS).')
                self.publish_heartbeat()

            elif action == 'restart_analytics':
                self.publish_result(command_id, action, 'completed', 'Jetson Nano: Da khoi dong lai luong phan tich DeepStream.')

            elif action == 'reload_config':
                params = data.get('params') or data.get('config') or {}
                source_path = params.get('source_path') or data.get('video_filename') or 'test.mp4'
                w = params.get('road_width_m', 7.5)
                l = params.get('road_length_m', 50.0)
                video_display = os.path.basename(str(source_path))
            elif action == 'start_pipeline':
                self.publish_result(command_id, action, 'completed', {'pid': 9999, 'message': 'Pipeline simulator started.'})

            elif action == 'stop_pipeline':
                self.publish_result(command_id, action, 'completed', {'message': 'Pipeline simulator stopped.'})

            else:
                self.publish_result(command_id, action, 'not_implemented', 'Chua ho tro lenh: %s' % action)
        except Exception as e:
            print("[CMD ERROR] %s" % e)

    def publish_result(self, command_id, action, status, message):
        res = {
            'command_id': command_id,
            'action': action,
            'status': status,
            'message': message,
            'timestamp': iso_now(),
        }
        self.client.publish(TOPIC_COMMAND_RESULT, json.dumps(res), qos=1)
        print("[CMD RESULT PUBLISHED] %s -> %s" % (action, status))

    def publish_heartbeat(self):
        hb = {
            'edge_id': EDGE_ID,
            'camera_id': CAMERA_ID,
            'status': 'online',
            'service_status': 'running',
            'model_version': 'exp.engine (YOLOv8s + NvDCF)',
            'last_sequence': self.sequence,
            'timestamp': iso_now(),
        }
        self.client.publish(TOPIC_HEARTBEAT, json.dumps(hb), qos=1)
        print("[HEARTBEAT] Published online status")

    def telemetry_loop(self):
        while self.running:
            try:
                self.sequence += 1
                t = time.time()
                # Subtle variations
                self.vehicle_count = max(8, int(22 + 8 * math.sin(t / 40.0) + random.randint(-2, 2)))
                self.avg_speed = round(max(5.0, 18.0 - (self.vehicle_count - 15) * 0.8 + random.uniform(-1, 1)), 1)
                self.status = 'CONGESTED' if self.vehicle_count > 26 else ('SLOW' if self.vehicle_count > 16 else 'FREE')
                congestion_score = min(100, max(10, int(self.vehicle_count * 2.8 - self.avg_speed * 1.5)))

                edge_metrics = {
                    'fps': round(27.8 + random.uniform(-1.5, 1.5), 1),
                    'inference_latency_ms': 33.2,
                    'cpu_percent': random.randint(48, 58),
                    'cpu_usage_pct': random.randint(48, 58),
                    'gpu_percent': random.randint(68, 79),
                    'gpu_usage_pct': random.randint(68, 79),
                    'ram_percent': random.randint(62, 66),
                    'ram_usage_pct': random.randint(62, 66),
                    'temperature_c': round(56.5 + random.uniform(-0.8, 1.2), 1),
                    'offline_queue': 0,
                }

                payload = {
                    'schema_version': 1,
                    'message_id': str(uuid.uuid4()),
                    'sequence': self.sequence,
                    'edge_id': EDGE_ID,
                    'camera_id': CAMERA_ID,
                    'segment_id': SEGMENT_ID,
                    'timestamp': iso_now(),
                    'current_vehicle_count': self.vehicle_count,
                    'raw_tracks': self.vehicle_count + 4,
                    'counts_by_class': {
                        'motorcycle': int(self.vehicle_count * 0.65),
                        'car': int(self.vehicle_count * 0.25),
                        'truck': max(1, int(self.vehicle_count * 0.1)),
                    },
                    'avg_speed_kmh': self.avg_speed,
                    'median_speed_kmh': round(self.avg_speed * 0.95, 1),
                    'speed_by_class': {
                        'motorcycle': {'count': int(self.vehicle_count * 0.65), 'avg_speed_kmh': round(self.avg_speed * 1.05, 1)},
                        'car': {'count': int(self.vehicle_count * 0.25), 'avg_speed_kmh': round(self.avg_speed * 0.9, 1)},
                        'truck': {'count': max(1, int(self.vehicle_count * 0.1)), 'avg_speed_kmh': round(self.avg_speed * 0.75, 1)},
                    },
                    'density_veh_per_km_lane': round(self.vehicle_count * 1.5, 1),
                    'roi_entry_rate_veh_per_min': 28,
                    'estimated_flow_veh_per_min': round(self.vehicle_count * 1.15, 1),
                    'estimated_flow_veh_per_hour': round(self.vehicle_count * 69.0, 1),
                    'stopped_vehicle_count': max(0, int(self.vehicle_count * 0.25)),
                    'stopped_vehicle_ratio': 0.25 if self.vehicle_count > 20 else 0.1,
                    'traffic_status': self.status,
                    'congestion_score': congestion_score,
                    'forecast': {
                        'ready': True,
                        'forecast_5min': {'status': self.status, 'congestion_score': min(100, congestion_score + 5), 'confidence': 'MEDIUM'},
                        'forecast_10min': {'status': self.status, 'congestion_score': min(100, congestion_score + 8), 'confidence': 'MEDIUM'},
                    },
                    'edge_metrics': edge_metrics,
                }

                self.client.publish(TOPIC_TELEMETRY, json.dumps(payload), qos=0)
            except Exception as err:
                print("[TELEMETRY ERROR] %s" % err)

            time.sleep(1.0)

    def heartbeat_loop(self):
        while self.running:
            try:
                self.publish_heartbeat()
            except Exception as e:
                print("[HEARTBEAT ERROR] %s" % e)
            time.sleep(5.0)

    def start(self):
        print("[SIMULATOR] Starting Jetson Nano AI Simulator...")
        print("[SIMULATOR] Connecting to MQTT broker %s:%d..." % (MQTT_HOST, MQTT_PORT))
        self.client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
        self.client.loop_start()

        # Generate an initial snapshot immediately so the Web UI has a camera frame
        try:
            print("[SIMULATOR] Uploading initial reference camera frame to Backend...")
            jpeg = generate_test_frame(self.vehicle_count, self.avg_speed, self.status)
            if jpeg:
                upload_snapshot_to_backend(jpeg, str(uuid.uuid4()), {
                    'traffic_status': self.status,
                    'current_vehicle_count': self.vehicle_count,
                    'avg_speed_kmh': self.avg_speed,
                    'density_veh_per_km_lane': 35.0,
                    'estimated_flow_veh_per_min': 24.0,
                    'stopped_vehicle_ratio': 0.2,
                    'congestion_score': 42,
                })
        except Exception as err:
            print("[SIMULATOR] Initial snapshot notice: %s" % err)

        t_telemetry = threading.Thread(target=self.telemetry_loop, daemon=True)
        t_heartbeat = threading.Thread(target=self.heartbeat_loop, daemon=True)
        t_telemetry.start()
        t_heartbeat.start()

        print("[SIMULATOR] Jetson Nano simulator is ACTIVE!")
        print("[SIMULATOR] Telemetry publishing: 1s, Heartbeat: 5s, Listening for commands.")
        print("[SIMULATOR] Press Ctrl+C to stop.")

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n[SIMULATOR] Stopping...")
            self.running = False
            self.client.loop_stop()
            self.client.disconnect()

if __name__ == '__main__':
    sim = JetsonSimulator()
    sim.start()
