#!/usr/bin/env python3
"""
Script kiểm thử nhanh hiệu ứng Bản đồ nhiệt kẹt xe (Corridor Heatmap) trên WebGIS.
Gửi trực tiếp các mức nhiệt độ kẹt xe qua MQTT HiveMQ tới node edge-01 (Đoạn đường Nguyễn Văn Khối):
- Mức 1: Thông thoáng (Congestion Score = 15, Vận tốc 35 km/h) -> Xanh ngọc dịu
- Mức 2: Chớm chậm (Congestion Score = 50, Vận tốc 18 km/h) -> Vàng hổ phách + vầng nhiệt ấm
- Mức 3: Ùn tắc (Congestion Score = 82, Vận tốc 7 km/h) -> Đỏ rực bốc khói nhiệt (Thermal Halo)
- Mức 4: Kẹt cứng đứng bánh (Congestion Score = 98, Vận tốc 2 km/h) -> Tím nhiệt cực đại (Severe Thermal Jam)
"""

import os
import sys
import time
import json
import ssl
import uuid

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("[ERROR] Cần thư viện paho-mqtt. Chạy: pip install paho-mqtt")
    sys.exit(1)

MQTT_HOST = os.getenv('MQTT_HOST', '829e7cb26c594257a7470e5a5af58064.s1.eu.hivemq.cloud')
MQTT_PORT = int(os.getenv('MQTT_PORT', '8883'))
MQTT_USER = os.getenv('MQTT_USER', 'admin')
MQTT_PASS = os.getenv('MQTT_PASS', '12345678')
EDGE_ID = os.getenv('EDGE_ID', 'edge-01')
TOPIC = f'traffic/{EDGE_ID}/telemetry'

SCENARIOS = [
    {
        "name": "MỨC 1: ĐƯỜNG THÔNG THOÁNG (FREE)",
        "traffic_status": "FREE",
        "congestion_score": 15,
        "avg_speed_kmh": 36.5,
        "current_vehicle_count": 8,
        "stopped_vehicle_count": 0,
        "description": "Lõi đường màu xanh ngọc, không tỏa nhiệt."
    },
    {
        "name": "MỨC 2: CHỚM ĐÔNG XE (SLOW)",
        "traffic_status": "SLOW",
        "congestion_score": 52,
        "avg_speed_kmh": 19.2,
        "current_vehicle_count": 22,
        "stopped_vehicle_count": 2,
        "description": "Lõi đường chuyển màu vàng hổ phách, bắt đầu bốc quầng nhiệt ấm quanh mép đường."
    },
    {
        "name": "MỨC 3: ÙN TẮC GIAO THÔNG (CONGESTED)",
        "traffic_status": "CONGESTED",
        "congestion_score": 85,
        "avg_speed_kmh": 6.8,
        "current_vehicle_count": 38,
        "stopped_vehicle_count": 16,
        "description": "Lõi đường đỏ rực lửa, hào quang nhiệt (Thermal Halo) bốc tỏa mạnh ra ngoài vỉa hè."
    },
    {
        "name": "MỨC 4: KẸT CỨNG ĐỨNG BÁNH (CRITICAL CONGESTION)",
        "traffic_status": "CONGESTED",
        "congestion_score": 98,
        "avg_speed_kmh": 2.1,
        "current_vehicle_count": 45,
        "stopped_vehicle_count": 32,
        "description": "Lõi đường ngả tím đỏ nhiệt độ cao, quầng nhiệt tỏa rộng tối đa 100%!"
    }
]

def main():
    print("=" * 70)
    print("   CHƯƠNG TRÌNH TEST HIỆU ỨNG NHIỆT KẸT XE TRÊN WEBGIS")
    print(f"   Đang kết nối tới MQTT Broker: {MQTT_HOST}:{MQTT_PORT}...")
    print(f"   Mục tiêu: Node '{EDGE_ID}' (Đoạn đường Nguyễn Văn Khối)")
    print("=" * 70)

    client_id = f"heat-tester-{uuid.uuid4().hex[:6]}"
    client = mqtt.Client(client_id=client_id, clean_session=True)
    client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.tls_set(cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLS)

    try:
        client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
        client.loop_start()
        print(">> Đã kết nối MQTT Broker thành công!\n")
    except Exception as e:
        print(f"[LỖI KẾT NỐI] {e}")
        return

    step = 0
    try:
        while True:
            scenario = SCENARIOS[step % len(SCENARIOS)]
            print(f"\n-------------------------------------------------------------")
            print(f">>> [BƯỚC { (step % len(SCENARIOS)) + 1 }/4] {scenario['name']}")
            print(f"    • Điểm nhiệt kẹt xe: {scenario['congestion_score']}/100")
            print(f"    • Vận tốc trung bình: {scenario['avg_speed_kmh']} km/h")
            print(f"    • Lượng xe: {scenario['current_vehicle_count']} xe (dừng: {scenario['stopped_vehicle_count']} xe)")
            print(f"    • Hiệu ứng quan sát: {scenario['description']}")
            print(f"-------------------------------------------------------------")

            payload = {
                "edge_id": EDGE_ID,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+07:00"),
                "traffic_status": scenario["traffic_status"],
                "congestion_score": scenario["congestion_score"],
                "avg_speed_kmh": scenario["avg_speed_kmh"],
                "current_vehicle_count": scenario["current_vehicle_count"],
                "stopped_vehicle_count": scenario["stopped_vehicle_count"],
                "density_veh_per_km_lane": round(scenario["current_vehicle_count"] * 2.3, 1),
                "counts_by_class": {
                    "motorcycle": int(scenario["current_vehicle_count"] * 0.7),
                    "car": int(scenario["current_vehicle_count"] * 0.25),
                    "truck": max(0, scenario["current_vehicle_count"] - int(scenario["current_vehicle_count"] * 0.95))
                },
                "edge_metrics": {
                    "fps": 28.5,
                    "inference_latency_ms": 32.1,
                    "cpu_usage_pct": 52,
                    "gpu_usage_pct": 74,
                    "temperature_c": 58.2
                }
            }

            client.publish(TOPIC, json.dumps(payload), qos=0)
            print(f">> Đã gửi gói tin Telemetry tới topic: {TOPIC}")
            print(f">> Hãy mở trình duyệt xem bản đồ biến đổi màu và quầng nhiệt!")
            print(f">> Tự động chuyển nấc tiếp theo sau 8 giây... (Nhấn Ctrl+C để dừng)")

            step += 1
            time.sleep(8.0)

    except KeyboardInterrupt:
        print("\n[ĐÃ DỪNG] Đã ngắt kết nối.")
    finally:
        client.loop_stop()
        client.disconnect()

if __name__ == "__main__":
    main()
