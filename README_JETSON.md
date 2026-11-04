# 🚀 HƯỚNG DẪN TRIỂN KHAI JETSON EDGE AI TRAFFIC MONITORING

Gói triển khai gọn nhẹ tối ưu dành riêng cho thiết bị biên NVIDIA Jetson Nano (JetPack 4.x / DeepStream 6.x).

## 1. Cài đặt thư viện phụ thuộc
```bash
sudo apt-get update && sudo apt-get install -y python3-pip libgstreamer1.0-dev
pip3 install -r requirements.txt
```

## 2. Cấu hình hệ thống
Chỉnh sửa file `.env` phù hợp với mạng thực địa:
- `BACKEND_URL`: Địa chỉ máy chủ WebGIS (ví dụ: `http://192.168.1.100:8000`)
- `MQTT_HOST`, `MQTT_USER`, `MQTT_PASS`: Thông tin kết nối MQTT Broker
- `ANALYTICS_SOURCE`: `csi` (Camera CSI thực tế) hoặc `file` (video thử nghiệm trong Video/)
- `LIVE_STREAM_ENABLED`: 1 (bật truyền luồng RTSP về WebGIS)

## 3. Khởi chạy
```bash
chmod +x restart_edge.sh
python3 main.py
# Hoặc khởi động qua script:
./restart_edge.sh
```
