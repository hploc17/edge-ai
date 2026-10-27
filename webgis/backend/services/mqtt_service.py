import asyncio
import json
import ssl
import threading
import time
import uuid
from datetime import datetime
import paho.mqtt.client as mqtt_lib

try:
    from config import MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASS, MQTT_CLIENT_ID
    from services.data_store import store
    from services.websocket_manager import ws_manager
except ImportError:
    from webgis.backend.config import MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASS, MQTT_CLIENT_ID
    from webgis.backend.services.data_store import store
    from webgis.backend.services.websocket_manager import ws_manager

class MQTTService:
    """MQTT Client service to communicate with Edge AI Jetson nodes."""

    def __init__(self):
        self._client = None
        self._connected = False
        self._loop = None
        self._thread = None
        self._stop_event = threading.Event()

    def start(self, event_loop: asyncio.AbstractEventLoop):
        self._loop = event_loop
        # Dùng Client ID cố định và clean_session=True để không làm tăng rác session trên MQTT Broker (HiveMQ)
        self._client = mqtt_lib.Client(client_id=MQTT_CLIENT_ID, clean_session=True)
        self._client.username_pw_set(MQTT_USER, MQTT_PASS)

        if MQTT_PORT == 8883:
            self._client.tls_set(cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLS)

        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

        try:
            print(f"[MQTT] Connecting to broker {MQTT_HOST}:{MQTT_PORT}...")
            self._client.connect_async(MQTT_HOST, MQTT_PORT, keepalive=60)
            self._client.loop_start()
        except Exception as e:
            print(f"[MQTT] Connect error: {e}")

        # Kiểm tra biến ENABLE_SIMULATION: mặc định tắt để chỉ đọc dữ liệu thật từ Jetson
        import os
        enable_sim = os.getenv("ENABLE_SIMULATION", "false").lower() in ("true", "1", "yes")
        if enable_sim:
            print("[SIMULATION] Live traffic simulation is ENABLED.")
            self._thread = threading.Thread(target=self._live_simulation_loop, daemon=True)
            self._thread.start()
        else:
            print("[SIMULATION] Live traffic simulation is DISABLED. Only real node telemetry will be displayed.")

    def stop(self):

        self._stop_event.set()
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self._connected = True
            print("[MQTT] Successfully connected to MQTT Broker!")
            # Subscribe to all edge traffic topics
            client.subscribe("traffic/+/telemetry", qos=0)
            client.subscribe("traffic/+/registration", qos=1)
            client.subscribe("traffic/+/device-health", qos=1)
            client.subscribe("traffic/+/heartbeat", qos=1)
            client.subscribe("traffic/+/liveness", qos=1)
            client.subscribe("traffic/discovery/announce", qos=1)
            client.subscribe("traffic/+/command-result", qos=1)
            client.subscribe("traffic/hw/+/command-result", qos=1)
            print("[MQTT] Subscribed to traffic/+/+, traffic/hw/+/+, and traffic/discovery/announce topics")
        else:
            print(f"[MQTT] Connection failed with code: {rc}")

    def _on_disconnect(self, client, userdata, rc):
        self._connected = False
        print(f"[MQTT] Disconnected (code={rc})")

    def _on_message(self, client, userdata, msg):
        try:
            topic = msg.topic
            parts = topic.split('/')
            payload = json.loads(msg.payload.decode("utf-8"))

            # Xử lý bản tin ZTP Auto-Discovery Báo danh
            if topic == "traffic/discovery/announce" or (len(parts) >= 3 and parts[2] == "announce"):
                ztp_res = store.process_ztp_announcement(payload)
                if ztp_res["action"] == "resumed":
                    self._broadcast_async({
                        "type": "node_registered",
                        "edge_id": ztp_res["edge_id"],
                        "node": ztp_res["node"]
                    })
                else:
                    self._broadcast_async({
                        "type": "device_pending",
                        "edge_id": ztp_res["edge_id"],
                        "mac_address": ztp_res["node"].get("mac_address"),
                        "require_setup": True,
                        "node": ztp_res["node"],
                        "pending_count": len(store.pending_nodes)
                    })
                return

            if len(parts) >= 4 and parts[1] == "hw":
                clean_mac = parts[2]
                subtopic = parts[3]
                mapped_node = store.get_node_by_mac(clean_mac)
                edge_id = mapped_node["edge_id"] if mapped_node else clean_mac
            elif len(parts) >= 3:
                edge_id = parts[1]
                subtopic = parts[2]
            else:
                return

            # Trích xuất địa chỉ MAC phần cứng nếu có trong payload
            mac_addr = payload.get("mac_address")
            if not mac_addr and isinstance(payload.get("latest_health"), dict):
                mac_addr = payload["latest_health"].get("network", {}).get("mac_address")
            if not mac_addr and isinstance(payload.get("network"), dict):
                mac_addr = payload["network"].get("mac_address")
            if mac_addr:
                mac_addr = str(mac_addr).strip().upper()
                payload["mac_address"] = mac_addr

            serial_num = payload.get("serial_number")
            reported_lat = payload.get("latitude")
            reported_lon = payload.get("longitude")

            if subtopic == "telemetry":
                approved_node = (store.get_node_by_mac(mac_addr) if mac_addr else None) or store.get_node(edge_id)
                if approved_node:
                    target_id = approved_node["edge_id"]
                    if not payload.get("segment_id") and approved_node.get("segment_id"):
                        payload["segment_id"] = approved_node["segment_id"]
                    store.update_telemetry(target_id, payload)
                    self._broadcast_async({
                        "type": "telemetry",
                        "edge_id": target_id,
                        "coordinates": [float(approved_node.get("longitude", 106.65)), float(approved_node.get("latitude", 10.84))],
                        "data": payload
                    })
                    seg_id = approved_node.get("segment_id")
                    if seg_id:
                        seg = store.get_segment(seg_id)
                        if seg:
                            self._broadcast_async({
                                "type": "segment_update",
                                "segment_id": seg_id,
                                "data": seg
                            })
                else:
                    # Node CHƯA được phê duyệt → chỉ cập nhật hàng chờ pending
                    is_new = edge_id not in store.pending_nodes and (not mac_addr or not store.get_pending_by_mac(mac_addr))
                    store.add_pending_node(edge_id, payload) if is_new else store.touch_pending(edge_id, payload)
                    if is_new:
                        print(f"[MQTT] New unapproved device detected from telemetry: {edge_id} (MAC: {mac_addr})")
                        self._broadcast_async({
                            "type": "device_pending",
                            "edge_id": edge_id,
                            "mac_address": mac_addr,
                            "require_setup": True,
                            "node": store.get_pending_node(edge_id),
                            "pending_count": len(store.pending_nodes)
                        })

            elif subtopic in ("registration", "heartbeat"):
                payload["edge_id"] = edge_id
                approved_node = (store.get_node_by_mac(mac_addr) if mac_addr else None) or store.get_node(edge_id)

                if approved_node:
                    approved_edge_id = approved_node["edge_id"]
                    node = store.nodes[approved_edge_id]
                    node["status"] = "online"
                    node["last_seen"] = payload.get("timestamp") or time.strftime("%Y-%m-%dT%H:%M:%S+07:00")
                    if mac_addr and not node.get("mac_address"):
                        node["mac_address"] = mac_addr
                    if serial_num and not node.get("serial_number"):
                        node["serial_number"] = serial_num
                    for key in ("model_version", "camera_id"):
                        if payload.get(key):
                            node[key] = payload[key]

                    # ── Đối chiếu 1: Kiểm tra lệch mã định danh logic (ID Mismatch) ──
                    if edge_id != approved_edge_id and edge_id != "hw":
                        node["actual_hardware_id"] = edge_id
                        node["id_mismatch"] = True
                        node["mismatch_message"] = f"Thiết bị tự xưng là '{edge_id}', mã quản lý Web là '{approved_edge_id}'."
                        self._broadcast_async({
                            "type": "node_mismatch_warning",
                            "edge_id": approved_edge_id,
                            "actual_hardware_id": edge_id,
                            "mac_address": mac_addr,
                            "message": f"Phát hiện sai lệch mã định danh: Thiết bị gửi '{edge_id}', mã quản trị là '{approved_edge_id}'. Điều khiển tự động qua MAC đang hoạt động."
                        })
                    else:
                        node["id_mismatch"] = False
                        node.pop("mismatch_message", None)

                    # ── Đối chiếu 2: Kiểm tra sai lệch vị trí địa lý GPS (Spatial Drift) ──
                    if reported_lat is not None and reported_lon is not None:
                        try:
                            import math
                            rlat = float(reported_lat)
                            rlon = float(reported_lon)
                            slat = float(node.get("latitude", 0))
                            slon = float(node.get("longitude", 0))
                            if slat != 0 and slon != 0 and rlat != 0 and rlon != 0:
                                dlat = math.radians(rlat - slat)
                                dlon = math.radians(rlon - slon)
                                a = math.sin(dlat / 2.0)**2 + math.cos(math.radians(slat)) * math.cos(math.radians(rlat)) * math.sin(dlon / 2.0)**2
                                drift_m = 6371000.0 * 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
                                if drift_m > 100.0:
                                    node["spatial_drift"] = {
                                        "drift_m": round(drift_m, 1),
                                        "reported_coords": [rlat, rlon],
                                        "saved_coords": [slat, slon]
                                    }
                                    self._broadcast_async({
                                        "type": "spatial_drift_warning",
                                        "edge_id": approved_edge_id,
                                        "drift_m": round(drift_m, 1),
                                        "reported_coords": [rlat, rlon],
                                        "saved_coords": [slat, slon],
                                        "message": f"Cảnh báo di dời: Tọa độ GPS của trạm '{approved_edge_id}' lệch {round(drift_m, 1)}m so với vị trí đã lưu trên bản đồ."
                                    })
                                else:
                                    node.pop("spatial_drift", None)
                        except Exception:
                            pass

                    store._persist_nodes()
                    event_type = "node_registered" if subtopic == "registration" else "heartbeat"
                    self._broadcast_async({
                        "type": event_type,
                        "edge_id": approved_edge_id,
                        "status": node["status"],
                        "coordinates": [float(node.get("longitude", 106.65)), float(node.get("latitude", 10.84))],
                        "last_seen": node["last_seen"],
                        "node": store.get_node(approved_edge_id)
                    })
                else:
                    # Thiết bị mới hoàn toàn → thêm vào pending
                    is_new = edge_id not in store.pending_nodes and (not mac_addr or not store.get_pending_by_mac(mac_addr))
                    pending_info = {
                        "edge_id": edge_id,
                        "mac_address": mac_addr,
                        "serial_number": serial_num,
                        "camera_id": payload.get("camera_id", "camera-01"),
                        "status": "pending_setup",
                        "latitude": reported_lat,
                        "longitude": reported_lon,
                        "road_name": payload.get("road_name"),
                        "raw_payload": payload,
                    }
                    store.add_pending_node(edge_id, pending_info) if is_new else store.touch_pending(edge_id, payload)
                    if is_new:
                        print(f"[MQTT] New unapproved device detected from {subtopic}: {edge_id} (MAC: {mac_addr or 'N/A'})")
                        self._broadcast_async({
                            "type": "device_pending",
                            "edge_id": edge_id,
                            "mac_address": mac_addr,
                            "require_setup": True,
                            "node": store.get_pending_node(edge_id),
                            "pending_count": len(store.pending_nodes)
                        })

            elif subtopic == "device-health":
                store.update_node_health(edge_id, payload)
                self._broadcast_async({
                    "type": "device_health",
                    "edge_id": edge_id,
                    "command_id": payload.get("command_id"),
                    "health": payload
                })

            elif subtopic == "command-result":
                command_id = payload.get("command_id", "")
                try:
                    from routers.remote_control import notify_command_result
                    notify_command_result(command_id, payload)
                except Exception as ex:
                    print(f"[MQTT] notify_command_result error: {ex}")

                effective_edge_id = edge_id
                if mac_addr:
                    mapped_node = store.get_node_by_mac(mac_addr)
                    if mapped_node:
                        effective_edge_id = mapped_node["edge_id"]

                self._broadcast_async({
                    "type": "command_result",
                    "edge_id": effective_edge_id,
                    "command_id": command_id,
                    "action": payload.get("action", ""),
                    "status": payload.get("status", ""),
                    "message": payload.get("message", ""),
                    "timestamp": payload.get("timestamp", ""),
                })

        except Exception as e:
            print(f"[MQTT PARSE ERROR] {e}")

    def _broadcast_async(self, message: dict):
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(ws_manager.broadcast(message), self._loop)

    def publish_command(self, edge_id: str, action: str, command_id: str, params: dict = None) -> bool:
        """Publish remote command to logic topic, hardware topic (via MAC), and alias topic."""
        node = store.get_node(edge_id)
        mac_addr = node.get("mac_address") if node else None
        actual_hw_id = node.get("actual_hardware_id") if node else None

        payload = {
            "action": action,
            "command_id": command_id,
            "params": params or {},
            "target_edge_id": edge_id,
            "mac_address": mac_addr,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+07:00")
        }
        raw_msg = json.dumps(payload, ensure_ascii=False)

        if self._client and self._connected:
            published = False
            # 1. Primary Logic Topic: traffic/{edge_id}/command
            try:
                topic = f"traffic/{edge_id}/command"
                self._client.publish(topic, raw_msg, qos=1)
                published = True
                print(f"[MQTT CMD] Sent {action} (ID={command_id}) to {topic}")
            except Exception as e:
                print(f"[MQTT CMD ERROR] {topic}: {e}")

            # 2. Hardware-Centric Topic: traffic/hw/{clean_mac}/command
            if mac_addr:
                clean_mac = str(mac_addr).replace(":", "").replace("-", "").strip().lower()
                if clean_mac and clean_mac != "000000000000":
                    hw_topic = f"traffic/hw/{clean_mac}/command"
                    try:
                        self._client.publish(hw_topic, raw_msg, qos=1)
                        published = True
                        print(f"[MQTT CMD] Sent {action} (ID={command_id}) to HW topic {hw_topic}")
                    except Exception as e:
                        print(f"[MQTT CMD ERROR] {hw_topic}: {e}")

            # 3. Alias Topic: traffic/{actual_hardware_id}/command
            if actual_hw_id and actual_hw_id != edge_id:
                alias_topic = f"traffic/{actual_hw_id}/command"
                try:
                    self._client.publish(alias_topic, raw_msg, qos=1)
                    published = True
                    print(f"[MQTT CMD] Sent {action} (ID={command_id}) to alias topic {alias_topic}")
                except Exception as e:
                    print(f"[MQTT CMD ERROR] {alias_topic}: {e}")

            return published
        else:
            # Fallback simulated response if MQTT broker is offline
            print(f"[MQTT LOCAL] Broker not connected, simulated command: {action}")
            if action == "get_health":
                if node:
                    health = node.get("latest_health", {})
                    self._broadcast_async({
                        "type": "device_health",
                        "edge_id": edge_id,
                        "command_id": command_id,
                        "health": health
                    })
            return True

    def _live_simulation_loop(self):
        """Simulate micro-variations in traffic telemetry every 3 seconds to keep WebGIS alive."""
        import random
        while not self._stop_event.is_set():
            time.sleep(3.0)
            for node in store.get_all_nodes():
                edge_id = node["edge_id"]
                current_count = max(5, min(60, node.get("current_vehicle_count", 20) + random.randint(-2, 2)))
                avg_speed = max(8.0, min(55.0, node.get("avg_speed_kmh", 25.0) + random.uniform(-1.5, 1.5)))
                
                # Quy đổi xe con PCE theo TCVN 4054:2005 (xe máy 0.3, ô tô 1.0, xe tải/buýt 1.8)
                pce_count = (current_count * 0.70) * 0.30 + (current_count * 0.20) * 1.0 + (current_count * 0.10) * 1.8
                pce_density = round(pce_count / 0.1, 1)

                # Priority Gating logic (Việt Nam mixed traffic)
                if avg_speed >= 22.0:
                    status = "FREE"
                    stopped_ratio = random.uniform(0.0, 0.05)
                elif avg_speed <= 10.0:
                    status = "CONGESTED"
                    stopped_ratio = random.uniform(0.28, 0.45)
                else:
                    status = "SLOW"
                    stopped_ratio = random.uniform(0.10, 0.20)

                # Congestion score 0-100: 50% Speed + 30% Stopped + 20% Density
                speed_penalty = min(50.0, max(0.0, 50.0 * (1.0 - avg_speed / 25.0)))
                stopped_penalty = min(30.0, max(0.0, 30.0 * (stopped_ratio / 0.35)))
                density_penalty = min(20.0, max(0.0, 20.0 * (pce_density / 220.0)))
                score = max(5, min(100, int(speed_penalty + stopped_penalty + density_penalty)))

                telemetry = {
                    "edge_id": edge_id,
                    "traffic_status": status,
                    "congestion_score": score,
                    "avg_speed_kmh": round(avg_speed, 1),
                    "current_vehicle_count": current_count,
                    "stopped_vehicle_count": int(current_count * 0.3) if status == "CONGESTED" else random.randint(0, 2),
                    "density_veh_per_km_lane": round(current_count * 2.3, 1),
                    "counts_by_class": {
                        "motorcycle": int(current_count * 0.65),
                        "car": int(current_count * 0.25),
                        "bus": max(0, int(current_count * 0.05)),
                        "truck": max(0, int(current_count * 0.05))
                    }
                }
                store.update_telemetry(edge_id, telemetry)
                self._broadcast_async({
                    "type": "telemetry",
                    "edge_id": edge_id,
                    "data": telemetry
                })


mqtt_service = MQTTService()
