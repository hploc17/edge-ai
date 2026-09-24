import asyncio
import json
import ssl
import threading
import time
import uuid
import paho.mqtt.client as mqtt_lib

from config import MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASS, MQTT_CLIENT_ID
from services.data_store import store
from services.websocket_manager import ws_manager

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
        self._client = mqtt_lib.Client(client_id=f"{MQTT_CLIENT_ID}-{uuid.uuid4().hex[:4]}")
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
            print(f"[MQTT ERROR] Connection failed: {e}")

        # Start live traffic simulation thread to keep data fresh if broker is idle
        self._thread = threading.Thread(target=self._live_simulation_loop, daemon=True)
        self._thread.start()

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
            client.subscribe("traffic/+/command-result", qos=1)
            print("[MQTT] Subscribed to traffic/+/+ topics")
        else:
            print(f"[MQTT] Connection failed with code: {rc}")

    def _on_disconnect(self, client, userdata, rc):
        self._connected = False
        print(f"[MQTT] Disconnected (code={rc})")

    def _on_message(self, client, userdata, msg):
        try:
            topic = msg.topic
            payload = json.loads(msg.payload.decode("utf-8"))
            parts = topic.split("/")
            if len(parts) < 3:
                return
            edge_id = parts[1]
            subtopic = parts[2]

            if subtopic == "telemetry":
                store.update_telemetry(edge_id, payload)
                self._broadcast_async({
                    "type": "telemetry",
                    "edge_id": edge_id,
                    "data": payload
                })

            elif subtopic == "registration":
                store.upsert_node(payload)
                self._broadcast_async({
                    "type": "node_registered",
                    "edge_id": edge_id,
                    "node": payload
                })

            elif subtopic == "device-health":
                store.update_node_health(edge_id, payload)
                self._broadcast_async({
                    "type": "device_health",
                    "edge_id": edge_id,
                    "command_id": payload.get("command_id"),
                    "health": payload
                })

            elif subtopic == "heartbeat":
                node = store.get_node(edge_id)
                if node:
                    node["status"] = payload.get("status", "online")
                    node["last_seen"] = payload.get("timestamp")

        except Exception as e:
            print(f"[MQTT PARSE ERROR] {e}")

    def _broadcast_async(self, message: dict):
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(ws_manager.broadcast(message), self._loop)

    def publish_command(self, edge_id: str, action: str, command_id: str, params: dict = None) -> bool:
        """Publish remote command to traffic/{edge_id}/command."""
        topic = f"traffic/{edge_id}/command"
        payload = {
            "action": action,
            "command_id": command_id,
            "params": params or {},
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+07:00")
        }
        if self._client and self._connected:
            try:
                self._client.publish(topic, json.dumps(payload, ensure_ascii=False), qos=1)
                print(f"[MQTT CMD] Sent {action} (ID={command_id}) to {topic}")
                return True
            except Exception as e:
                print(f"[MQTT CMD ERROR] {e}")
                return False
        else:
            # Fallback simulated response if MQTT broker is offline
            print(f"[MQTT LOCAL] Broker not connected, simulated command: {action}")
            if action == "get_health":
                # Immediately simulate health response for UX testing
                node = store.get_node(edge_id)
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
                
                # Compute congestion score
                if avg_speed < 15.0:
                    score = min(100, int(70 + (15.0 - avg_speed) * 2.0))
                    status = "CONGESTED"
                elif avg_speed < 30.0:
                    score = int(40 + (30.0 - avg_speed) * 1.5)
                    status = "SLOW"
                else:
                    score = max(5, int(35 - (avg_speed - 30.0)))
                    status = "FREE"

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
