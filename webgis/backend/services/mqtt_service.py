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
            self._client.connect_async(MQTT_HOST, MQTT_PORT, keepalive=15)
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
            print("[MQTT] Subscribed to traffic/+/+ and traffic/discovery/announce topics")
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

            if len(parts) >= 3:
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
                target_nodes = []
                direct_node = store.get_node(edge_id)
                if direct_node:
                    target_nodes.append(direct_node)
                if mac_addr:
                    mac_node = store.get_node_by_mac(mac_addr)
                    if mac_node and mac_node not in target_nodes:
                        target_nodes.append(mac_node)
                for nid, n in store.nodes.items():
                    if n.get("actual_hardware_id") == edge_id and n not in target_nodes:
                        target_nodes.append(n)

                if target_nodes:
                    for approved_node in target_nodes:
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
                    # Dùng thời gian nhận tại Server cho liveness, miễn nhiễm với sai lệch đồng hồ Edge (Fix D5)
                    node["last_seen"] = datetime.now().isoformat()
                    node["device_reported_time"] = payload.get("timestamp")
                    if mac_addr and not node.get("mac_address"):
                        node["mac_address"] = mac_addr
                    if serial_num and not node.get("serial_number"):
                        node["serial_number"] = serial_num
                    for key in ("model_version", "camera_id"):
                        if payload.get(key):
                            node[key] = payload[key]
                    if "pipeline_running" in payload:
                        # Kiểm tra xem telemetry có đang hoạt động trong vòng 15s gần nhất không
                        last_telem = node.get("last_telemetry_at")
                        recent_telem = False
                        if last_telem:
                            try:
                                dt = datetime.fromisoformat(last_telem)
                                recent_telem = (datetime.now() - dt).total_seconds() < 15.0
                            except Exception:
                                pass
                        if recent_telem:
                            node["pipeline_running"] = True
                        else:
                            node["pipeline_running"] = bool(payload["pipeline_running"])
                            node["pipeline_pid"] = payload.get("pipeline_pid")
                    elif subtopic == "registration":
                        node["pipeline_running"] = False
                        node["pipeline_pid"] = None

                    # Đồng bộ sang các node quản trị liên kết khác (nếu có)
                    for other_id, other_node in store.nodes.items():
                        if other_node.get("actual_hardware_id") == edge_id and other_id != approved_edge_id:
                            other_node["status"] = node["status"]
                            other_node["last_seen"] = node["last_seen"]
                            other_node["pipeline_running"] = node.get("pipeline_running", False)
                            other_node["pipeline_pid"] = node.get("pipeline_pid")

                    # ── Đối chiếu 1: Kiểm tra lệch mã định danh logic (ID Mismatch) (Fix L9) ──
                    if edge_id != approved_edge_id:
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

                    # ── Đối chiếu 2: Kiểm tra sai lệch vị trí địa lý GPS (Spatial Drift) (Fix L9) ──
                    # CHỈ kiểm tra nếu có GPS phần cứng thực tế (vd module NEO-7M báo has_gps=True).
                    # Tuyệt đối không so sánh 2 số tĩnh nhập tay để tránh cảnh báo giả lệch 1131km.
                    hw_gps = payload.get("hardware_gps") or (payload.get("latest_health") or {}).get("hardware_gps")
                    if isinstance(hw_gps, dict) and hw_gps.get("has_gps") and hw_gps.get("latitude") and hw_gps.get("longitude"):
                        try:
                            import math
                            rlat = float(hw_gps["latitude"])
                            rlon = float(hw_gps["longitude"])
                            slat = float(node.get("latitude", 0))
                            slon = float(node.get("longitude", 0))
                            if slat != 0 and slon != 0 and rlat != 0 and rlon != 0:
                                dlat = math.radians(rlat - slat)
                                dlon = math.radians(rlon - slon)
                                a = math.sin(dlat / 2.0)**2 + math.cos(math.radians(slat)) * math.cos(math.radians(rlat)) * math.sin(dlon / 2.0)**2
                                drift_m = 6371000.0 * 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
                                if drift_m > 50.0:
                                    node["spatial_drift"] = {
                                        "drift_m": round(drift_m, 1),
                                        "reported_coords": [rlat, rlon],
                                        "saved_coords": [slat, slon],
                                        "is_hardware_gps": True
                                    }
                                    self._broadcast_async({
                                        "type": "spatial_drift_warning",
                                        "edge_id": approved_edge_id,
                                        "drift_m": round(drift_m, 1),
                                        "reported_coords": [rlat, rlon],
                                        "saved_coords": [slat, slon],
                                        "message": f"Cảnh báo di dời phần cứng: GPS trạm '{approved_edge_id}' lệch {round(drift_m, 1)}m so với vị trí quy hoạch."
                                    })
                                else:
                                    node.pop("spatial_drift", None)
                        except Exception:
                            pass
                    else:
                        node.pop("spatial_drift", None)

                    # Chỉ ghi đĩa khi đăng ký mới (registration), không ghi đĩa định kỳ mỗi heartbeat (Fix D4)
                    if subtopic == "registration":
                        store._persist_nodes()

                    event_type = "node_registered" if subtopic == "registration" else "heartbeat"
                    # Gửi delta payload cho heartbeat, tránh dump toàn bộ object node gây nghẽn WS (Fix D4)
                    hb_msg = {
                        "type": event_type,
                        "edge_id": approved_edge_id,
                        "status": node["status"],
                        "coordinates": [float(node.get("longitude", 106.65)), float(node.get("latitude", 10.84))],
                        "last_seen": node["last_seen"],
                        "data_status": node.get("data_status", "live"),
                        "pipeline_running": node.get("pipeline_running", False)
                    }
                    if event_type == "node_registered":
                        hb_msg["node"] = store.get_node(approved_edge_id)
                    self._broadcast_async(hb_msg)
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
                target_nodes = []
                direct_node = store.get_node(edge_id)
                if direct_node:
                    target_nodes.append(direct_node)
                if mac_addr:
                    mac_node = store.get_node_by_mac(mac_addr)
                    if mac_node and mac_node not in target_nodes:
                        target_nodes.append(mac_node)
                for nid, n in store.nodes.items():
                    if n.get("actual_hardware_id") == edge_id and n not in target_nodes:
                        target_nodes.append(n)

                if not target_nodes:
                    store.update_node_health(edge_id, payload)
                    self._broadcast_async({
                        "type": "device_health",
                        "edge_id": edge_id,
                        "command_id": payload.get("command_id"),
                        "health": payload
                    })
                else:
                    for node_item in target_nodes:
                        tid = node_item["edge_id"]
                        store.update_node_health(tid, payload)
                        self._broadcast_async({
                            "type": "device_health",
                            "edge_id": tid,
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

                action = payload.get("action", "")
                status = payload.get("status", "")
                msg_val = payload.get("message", "")

                if action in ("start_pipeline", "start_csi"):
                    if status == "completed":
                        pid = msg_val.get("pid") if isinstance(msg_val, dict) else None
                        store.update_pipeline_status(effective_edge_id, running=True, pid=pid)
                elif action in ("stop_pipeline", "restart_analytics"):
                    store.update_pipeline_status(effective_edge_id, running=False)
                elif action == "request_status":
                    if isinstance(msg_val, dict):
                        is_running = msg_val.get("pipeline_running", False)
                        pid = msg_val.get("pid")
                        store.update_pipeline_status(effective_edge_id, running=is_running, pid=pid)

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
        """Publish remote command to logic topic ONLY (Single Source of Truth, Fix L1)."""
        payload = {
            "action": action,
            "command_id": command_id,
            "params": params or {},
            "target_edge_id": edge_id,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+07:00")
        }
        raw_msg = json.dumps(payload, ensure_ascii=False)

        if self._client and self._connected:
            topics = [f"traffic/{edge_id}/command"]
            node = store.get_node(edge_id)
            if node and node.get("actual_hardware_id") and node.get("actual_hardware_id") != edge_id:
                hw_topic = f"traffic/{node['actual_hardware_id']}/command"
                if hw_topic not in topics:
                    topics.append(hw_topic)

            success = False
            for topic in topics:
                try:
                    self._client.publish(topic, raw_msg, qos=1)
                    print(f"[MQTT CMD] Sent {action} (ID={command_id}) to {topic}")
                    success = True
                except Exception as e:
                    print(f"[MQTT CMD ERROR] {topic}: {e}")
            return success
        else:
            # Fallback simulated response if MQTT broker is offline
            print(f"[MQTT LOCAL] Broker not connected, simulated command: {action}")
            node = store.get_node(edge_id)
            if action == "get_health":
                if node:
                    health = node.get("latest_health", {})
                    self._broadcast_async({
                        "type": "device_health",
                        "edge_id": edge_id,
                        "command_id": command_id,
                        "data": health
                    })
            return False

    def publish_provisioning_approval(self, mac_address: str, assigned_edge_id: str, approved_data: dict = None) -> bool:
        """Send provisioning approval payload to the device using its hardware MAC address."""
        if not mac_address:
            return False
        clean_mac = str(mac_address).replace(":", "").replace("-", "").strip().lower()
        topic = f"traffic/provisioning/{clean_mac}"
        payload = {
            "event": "node_approved",
            "assigned_edge_id": assigned_edge_id,
            "mac_address": mac_address,
            "approved_at": time.strftime("%Y-%m-%dT%H:%M:%S+07:00"),
            "config": approved_data or {}
        }
        raw_msg = json.dumps(payload, ensure_ascii=False)
        if self._client and self._connected:
            try:
                self._client.publish(topic, raw_msg, qos=1)
                print(f"[ZTP PROVISION] Sent assigned_edge_id={assigned_edge_id} to {topic}")
                return True
            except Exception as e:
                print(f"[ZTP PROVISION ERROR] {topic}: {e}")
                return False
        return False

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


import sys

if "webgis.backend.services.mqtt_service" in sys.modules and hasattr(sys.modules["webgis.backend.services.mqtt_service"], "mqtt_service"):
    mqtt_service = sys.modules["webgis.backend.services.mqtt_service"].mqtt_service
elif "services.mqtt_service" in sys.modules and hasattr(sys.modules["services.mqtt_service"], "mqtt_service"):
    mqtt_service = sys.modules["services.mqtt_service"].mqtt_service
else:
    mqtt_service = MQTTService()

_curr_mod = sys.modules.get(__name__)
if _curr_mod:
    sys.modules["services.mqtt_service"] = _curr_mod
    sys.modules["webgis.backend.services.mqtt_service"] = _curr_mod


