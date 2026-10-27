#!/usr/bin/env python3
"""Module ZTP (Zero-Touch Provisioning) cho NVIDIA Jetson Nano.

Tự động trích xuất địa chỉ MAC phần cứng thực tế và gửi bản tin Báo danh
(Hardware Announcement) về WebGIS Backend qua MQTT khi khởi động thiết bị.
Hỗ trợ cơ chế LWT (Last Will and Testament) để báo ngắt kết nối an toàn.
"""

import json
import os
import socket
import sys
import time
import uuid
from pathlib import Path
import paho.mqtt.client as mqtt

# Đảm bảo import được config/settings nếu chạy trong project
SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


def get_hardware_mac():
    """Lấy địa chỉ MAC thực tế từ nhân Linux (/sys/class/net/eth0/address)."""
    for iface in ['eth0', 'wlan0', 'enP2p1s0', 'en0']:
        mac_path = f"/sys/class/net/{iface}/address"
        if os.path.exists(mac_path):
            try:
                with open(mac_path, "r") as f:
                    mac = f.read().strip().upper()
                    if mac and len(mac) == 17:
                        return mac
            except Exception:
                pass

    # Fallback qua thư viện uuid nếu không đọc được sysfs (hoặc chạy trên Windows/Docker)
    raw_mac = uuid.getnode()
    formatted = ':'.join(f"{(raw_mac >> ele) & 0xff:02X}" for ele in range(40, -1, -8))
    return formatted


def get_local_ip():
    """Lấy địa chỉ IP cục bộ thực tế của card mạng đang kết nối Internet."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip


def build_ztp_payload(edge_id=None):
    """Đóng gói bản tin thông số phần cứng ZTP."""
    mac_address = get_hardware_mac()
    local_ip = get_local_ip()

    return {
        "event": "node_announced",
        "edge_id": edge_id or os.getenv("EDGE_ID", "edge-01"),
        "mac_address": mac_address,
        "ip_address": local_ip,
        "hardware_profile": {
            "soc": "NVIDIA Tegra X1 (Maxwell GPU 128 CUDA Cores)",
            "ram": "4GB LPDDR4 Unified Memory",
            "camera_sensor": "Sony IMX219 (CSI-2 2-Lane)",
            "camera_resolution": "1280x720@30fps",
            "os": "Ubuntu 18.04 LTS (JetPack 4.6.1 - L4T R32.7.1)",
            "deepstream_version": "6.0.1",
            "model_engine": os.getenv("MODEL_VERSION", "yolo11n_fp16.engine")
        },
        "default_spatial": {
            "road_width_m": 7.0,
            "road_length_m": 20.0,
            "lane_count": 2,
            "traffic_context": os.getenv("TRAFFIC_CONTEXT", "signalized")
        },
        "timestamp": time.time(),
        "timestamp_iso": time.strftime("%Y-%m-%dT%H:%M:%S+07:00")
    }


def publish_ztp_announcement(broker_host=None, broker_port=None, username=None, password=None, edge_id=None):
    """Kết nối MQTT và phát bản tin ZTP Auto-Discovery lên broker."""
    host = broker_host or os.getenv("MQTT_HOST", "829e7cb26c594257a7470e5a5af58064.s1.eu.hivemq.cloud")
    port = int(broker_port or os.getenv("MQTT_PORT", 8883))
    user = username or os.getenv("MQTT_USER", "admin")
    pw = password or os.getenv("MQTT_PASS", "12345678")

    mac_address = get_hardware_mac()
    payload = build_ztp_payload(edge_id)
    target_edge_id = payload["edge_id"]

    client_id = f"ztp-boot-{mac_address.replace(':', '').lower()}"
    client = mqtt.Client(client_id=client_id, clean_session=True)
    if user and pw:
        client.username_pw_set(user, pw)

    if port == 8883:
        import ssl
        client.tls_set(cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLS)

    # Đăng ký LWT (Last Will and Testament) chuyên ngành Liveness Probe
    lwt_topic = f"traffic/{target_edge_id}/liveness"
    client.will_set(
        topic=lwt_topic,
        payload=json.dumps({
            "status": "offline",
            "edge_id": target_edge_id,
            "mac_address": mac_address,
            "reason": "ungraceful_disconnect",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+07:00")
        }),
        qos=1,
        retain=True
    )

    try:
        print(f"[ZTP] Connecting to MQTT Broker {host}:{port}...")
        client.connect(host, port, 60)
        client.loop_start()

        # 1. Phát bản tin Auto-Discovery Announcement
        discovery_topic = "traffic/discovery/announce"
        client.publish(discovery_topic, json.dumps(payload), qos=1, retain=False)
        print(f"[ZTP] Published announcement for MAC: {mac_address} to topic: {discovery_topic}")

        # 2. Phát bản tin Registration tương thích ngược
        reg_topic = f"traffic/{target_edge_id}/registration"
        client.publish(reg_topic, json.dumps(payload), qos=1, retain=False)

        # 3. Phát tín hiệu Liveness ban đầu (Online)
        client.publish(lwt_topic, json.dumps({
            "status": "online",
            "edge_id": target_edge_id,
            "mac_address": mac_address,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+07:00")
        }), qos=1, retain=True)

        time.sleep(1.0)
        client.loop_stop()
        client.disconnect()
        print("[ZTP] ZTP announcement completed successfully.")
        return True
    except Exception as e:
        print(f"[ZTP ERROR] Failed to publish ZTP announcement: {e}")
        return False


if __name__ == "__main__":
    publish_ztp_announcement()
