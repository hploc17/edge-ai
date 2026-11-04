# HƯỚNG DẪN KIỂM THỬ ĐỘC LẬP TỪNG CHẶNG (LIVE SMOKE TEST)

Tài liệu này hướng dẫn bạn kiểm thử độc lập luồng video từ Camera CSI Jetson Nano lên MediaMTX **trước khi khởi động pipeline phân tích AI chính** (`main.py`).

---

## 1. Chuẩn bị
1. **MediaMTX đang chạy trên máy tính PC (IP `192.168.88.193`):**
   - Đảm bảo các cổng `8554`, `8888`, `8889` đang mở trên firewall.
2. **Tiến trình `main.py` trên Jetson ĐANG TẮT:**
   - Để tránh xung đột camera CSI (`nvarguscamerasrc`), kiểm tra và tắt các tiến trình cũ:
     ```bash
     pkill -INT -f "python3.*main"
     ```
   - Nếu camera bị kẹt báo `Camera device is busy`, khởi động lại daemon cảm biến:
     ```bash
     sudo systemctl restart nvargus-daemon
     ```

---

## 2. Kiểm tra Plugin GStreamer trên Jetson
Chạy lệnh kiểm tra xem Jetson đã có plugin RTSP client hay chưa:
```bash
gst-inspect-1.0 rtspclientsink
```
- **Nếu báo `No such element or plugin 'rtspclientsink'`:**
  Chạy lệnh cài đặt bổ sung:
  ```bash
  sudo apt-get update && sudo apt-get install -y gstreamer1.0-rtsp
  ```
  *(Hoặc trong Docker container: `docker exec -it trafic_edge_container apt-get update && apt-get install -y gstreamer1.0-rtsp`)*

---

## 3. Chặng 1: Bắn luồng trực tiếp từ Camera CSI lên MediaMTX

Chạy lệnh pipeline `gst-launch-1.0` trên Jetson Nano:

```bash
gst-launch-1.0 nvarguscamerasrc sensor-id=0 ! \
    'video/x-raw(memory:NVMM),width=1280,height=720,framerate=15/1' ! \
    nvvidconv ! \
    'video/x-raw(memory:NVMM),format=I420,width=640,height=360' ! \
    nvv4l2h264enc bitrate=1500000 insert-sps-pps=true idrinterval=15 profile=0 ! \
    h264parse ! \
    rtspclientsink location=rtsp://192.168.88.193:8554/live/edge-01 protocols=tcp
```

**Giải thích các tham số kỹ thuật:**
- `nvarguscamerasrc sensor-id=0`: Đọc trực tiếp từ camera CSI phần cứng qua ISP Tegra.
- `width=640,height=360`: Hạ kích thước vừa vặn khung xem popup WebGIS.
- `nvv4l2h264enc`: Chip phần cứng NVENC nén H.264 (tốn 0% CPU).
- `profile=0` (hoặc `profile=Baseline`): Profile Baseline (tương thích tối đa với mọi trình duyệt, không dùng B-frame).
- `insert-sps-pps=true`: Chèn thông tin giải mã SPS/PPS vào từng chu kỳ.
- `idrinterval=15`: Phát 1 khung hình chính (I-frame/IDR) mỗi giây để người xem vào sau có hình ngay lập tức.
- `protocols=tcp`: Dùng TCP cho RTSP để chống rớt gói tin trong mạng LAN.

---

## 4. Chặng 2: Kiểm tra xem luồng trên PC

### 1. Xem qua WebRTC (Độ trễ < 500ms):
Mở trình duyệt Chrome/Edge trên PC truy cập:
`http://192.168.88.193:8889/live/edge-01`
-> Video mượt mà, độ trễ tức thì.

### 2. Xem qua LL-HLS:
Mở trình duyệt hoặc trình phát HLS:
`http://192.168.88.193:8888/live/edge-01`

### 3. Xem qua VLC Media Player:
Mở VLC -> `Media` -> `Open Network Stream` -> Nhập URL:
`rtsp://192.168.88.193:8554/live/edge-01`
-> Chọn Play.

---

## 5. Dọn dẹp sau khi kiểm tra
Nhấn `Ctrl+C` trên terminal Jetson để dừng lệnh `gst-launch-1.0`. Camera CSI sẽ được giải phóng an toàn để sẵn sàng cho `main.py`.
