# 🚀 HƯỚNG DẪN TRIỂN KHAI JETSON EDGE AI TRAFFIC MONITORING

Gói triển khai gọn nhẹ tối ưu dành riêng cho thiết bị biên NVIDIA Jetson Nano (JetPack 4.x / DeepStream 6.x).

## 1. Cài đặt thư viện phụ thuộc
```bash
sudo apt-get update && sudo apt-get install -y python3-pip libgstreamer1.0-dev
pip3 install -r requirements.txt
```

## 2. Cấu hình hệ thống

Để cấu hình SPI v3 và đọc kết quả từ WebGIS, xem
[hướng dẫn SPI v3 — WebGIS/Jetson](docs/traffic_classifier_v3.md).
Sau khi cập nhật mã trên Jetson, khởi động lại agent theo quy trình triển khai
đang sử dụng để nạp trình xử lý cấu hình mới. Trên WebGIS chọn v3, lưu ROI và
tham số, chờ xác nhận của Jetson rồi dừng/chạy lại pipeline với cấu hình remote.
Không chỉ thay frontend: worker và agent cũ sẽ không áp dụng đầy đủ các trường mới.

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
