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

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
try:
    from communication.live_stream_sender import LiveStreamSender
except ImportError:
    LiveStreamSender = None

# Configuration matching Backend
BACKEND_URL = os.getenv('BACKEND_URL', 'http://localhost:8000').rstrip('/')
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

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

try:
    from analytics.traffic_classifier import TrafficStateModel
except Exception:
    TrafficStateModel = None

class JetsonSimulator:
    def __init__(self):
        self.client = mqtt.Client(client_id=MQTT_CLIENT_ID)
        self.client.username_pw_set(MQTT_USER, MQTT_PASS)
        self.client.tls_set(cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLSv1_2)

        # Cấu hình Last Will and Testament (LWT) (Mục 4)
        will_payload = json.dumps({
            'edge_id': EDGE_ID,
            'camera_id': CAMERA_ID,
            'status': 'offline',
            'timestamp': iso_now(),
        })
        self.client.will_set(TOPIC_HEARTBEAT, payload=will_payload, qos=1, retain=False)

        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.sequence = 0
        self.running = True
        self.state_model = TrafficStateModel() if TrafficStateModel else None

        # State
        self.vehicle_count = 20
        self.avg_speed = 22.0
        self.status = 'FREE'
        self.last_congestion_snap = 0.0

        # On-Demand Live Streaming Sender
        if LiveStreamSender:
            self.live_sender = LiveStreamSender(
                backend_url=BACKEND_URL,
                edge_id=EDGE_ID,
                edge_token=EDGE_TOKEN,
                width=640,
                height=360,
                fps=10
            )
        else:
            self.live_sender = None

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print("[MQTT] Connected to HiveMQ Broker: %s:%d" % (MQTT_HOST, MQTT_PORT))
            client.subscribe(TOPIC_COMMAND, qos=1)
            print("[MQTT] Subscribed to command topic: %s" % TOPIC_COMMAND)
            self.publish_heartbeat()
        else:
            print("[MQTT] Connection refused with code: %d" % rc)

    def on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode('utf-8'))
            action = payload.get('action')
            command_id = payload.get('command_id', str(uuid.uuid4()))
            print("[CMD RECEIVED] Action: %s, ID: %s" % (action, command_id))

            if action in ('capture_test_snapshot', 'capture_snapshot'):
                print("[CMD] Manual snapshot request rejected (Feature decommissioned)")
                self.publish_result(command_id, action, 'completed', 'Manual snapshot disabled: Snapshots are automatically captured on CONGESTED traffic events.')

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
                msg = f'Jetson Nano: Da ghi de cau hinh, nap Homography ({l}m x {w}m) va tai khoi dong phan tich video "{video_display}" thanh cong!'
                self.publish_result(command_id, action, 'completed', msg)

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
                # Chu kỳ giao thông động mô phỏng thực tế: chuyển đổi giữa thông thoáng, đông xe và ùn ứ
                cycle = math.sin(t / 25.0)
                if cycle > 0.4:
                    # Tình huống: Dòng xe bị nghẽn (tốc độ chậm, có xe dừng)
                    self.vehicle_count = random.randint(24, 35)
                    self.avg_speed = round(random.uniform(7.0, 12.0), 1)
                    stopped_ratio = round(random.uniform(0.28, 0.45), 2)
                elif cycle > -0.2:
                    # Tình huống điển hình VN: Xe máy đông đúc nhưng vẫn trôi nhanh (20-26 km/h)
                    self.vehicle_count = random.randint(16, 25)
                    self.avg_speed = round(random.uniform(21.0, 26.5), 1)
                    stopped_ratio = round(random.uniform(0.02, 0.08), 2)
                else:
                    # Tình huống: Đường thoáng
                    self.vehicle_count = random.randint(8, 14)
                    self.avg_speed = round(random.uniform(28.0, 36.0), 1)
                    stopped_ratio = 0.0

                motorcycles = int(self.vehicle_count * 0.75)
                cars = int(self.vehicle_count * 0.20)
                trucks = max(0, self.vehicle_count - motorcycles - cars)

                # Quy đổi tương đương xe con PCE theo TCVN 4054:2005 (xe máy 0.3, ô tô 1.0, xe tải 1.8)
                # Đoạn đường 50m, 2 làn (0.05 km * 2 = 0.1)
                pce_count = motorcycles * 0.30 + cars * 1.0 + trucks * 1.8
                pce_density = round(pce_count / 0.1, 1)

                if self.state_model:
                    self.status, congestion_score = self.state_model.classify(
                        avg_speed_kmh=self.avg_speed,
                        density=pce_density,
                        stopped_ratio=stopped_ratio,
                        timestamp=t
                    )
                else:
                    if self.avg_speed >= 22.0 and stopped_ratio < 0.15:
                        self.status = 'FREE'
                        congestion_score = max(5, int(50.0 * (1.0 - self.avg_speed / 25.0) + 20.0 * (pce_density / 220.0)))
                    elif self.avg_speed < 10.0 or stopped_ratio >= 0.30:
                        self.status = 'CONGESTED'
                        congestion_score = min(100, int(50.0 * (1.0 - self.avg_speed / 25.0) + 30.0 * (stopped_ratio / 0.35) + 20.0 * (pce_density / 220.0)))
                    else:
                        self.status = 'SLOW'
                        congestion_score = min(60, int(50.0 * (1.0 - self.avg_speed / 25.0) + 30.0 * (stopped_ratio / 0.35) + 20.0 * (pce_density / 220.0)))

                stopped_count = int(self.vehicle_count * stopped_ratio)

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
                        'motorcycle': motorcycles,
                        'car': cars,
                        'truck': trucks,
                    },
                    'avg_speed_kmh': self.avg_speed,
                    'median_speed_kmh': round(self.avg_speed * 0.95, 1),
                    'speed_by_class': {
                        'motorcycle': {'count': motorcycles, 'avg_speed_kmh': round(self.avg_speed * 1.05, 1)},
                        'car': {'count': cars, 'avg_speed_kmh': round(self.avg_speed * 0.9, 1)},
                        'truck': {'count': trucks, 'avg_speed_kmh': round(self.avg_speed * 0.75, 1)},
                    },
                    'density_veh_per_km_lane': pce_density,
                    'roi_entry_rate_veh_per_min': 28,
                    'estimated_flow_veh_per_min': round(self.vehicle_count * 1.15, 1),
                    'estimated_flow_veh_per_hour': round(self.vehicle_count * 69.0, 1),
                    'stopped_vehicle_count': stopped_count,
                    'stopped_vehicle_ratio': stopped_ratio,
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

                # Chụp snapshot tự động khi phát hiện kẹt xe (CONGESTED) với cooldown 60s
                if self.status == 'CONGESTED':
                    now_s = time.time()
                    if (now_s - self.last_congestion_snap) >= 60.0:
                        self.last_congestion_snap = now_s
                        try:
                            snap_jpeg = generate_test_frame(self.vehicle_count, self.avg_speed, self.status)
                            if snap_jpeg:
                                upload_snapshot_to_backend(snap_jpeg, str(uuid.uuid4()), payload)
                                print("[SIMULATOR] >>> CONGESTION SNAPSHOT CAPTURED & UPLOADED TO BACKEND <<<")
                        except Exception as snap_err:
                            print("[SIMULATOR] Congestion snapshot upload error: %s" % snap_err)
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

    def live_stream_loop(self):
        """Phát luồng Live Video 10 FPS on-demand khi có người xem trên WebGIS."""
        while self.running:
            try:
                if self.live_sender and self.live_sender.is_streaming:
                    frame = generate_test_frame(self.vehicle_count, self.avg_speed, self.status)
                    if frame:
                        self.live_sender.send_frame(frame)
            except Exception:
                pass
            time.sleep(0.1)

    def start(self):
        print("[SIMULATOR] Starting Jetson Nano AI Simulator...")
        print("[SIMULATOR] Connecting to MQTT broker %s:%d..." % (MQTT_HOST, MQTT_PORT))
        self.client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
        self.client.loop_start()

        # Khởi động LiveStreamSender kết nối Ingest WebSocket tới Backend
        if self.live_sender:
            self.live_sender.start()
            t_live = threading.Thread(target=self.live_stream_loop, daemon=True)
            t_live.start()

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
        print("[SIMULATOR] Telemetry publishing: 1s, Heartbeat: 5s, Live Ingest: On-Demand.")
        print("[SIMULATOR] Press Ctrl+C to stop.")

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n[SIMULATOR] Stopping...")
            self.running = False
            if self.live_sender:
                self.live_sender.stop()
            self.client.loop_stop()
            self.client.disconnect()

if __name__ == '__main__':
    sim = JetsonSimulator()
    sim.start()
