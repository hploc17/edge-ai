# KẾ HOẠCH NÂNG CẤP VÀ CẢI TIẾN HỆ THỐNG EDGE AI & WEBGIS
> **Tài liệu lưu trữ kiến trúc, giải pháp vận hành tối ưu và lộ trình cải tiến (Roadmap)**  
> *Ngày khởi tạo: 26/10/2026*

---

## 1. Tổng quan vấn đề vận hành trên NVIDIA Jetson

Trong quá trình nghiên cứu và thử nghiệm hệ thống Edge AI Traffic:
* **Hạn chế trước đây:** 
  - Mỗi khi chỉnh sửa mã nguồn hoặc file cấu hình (`.env`, `roi_config.json`, `main.py`), người dùng phải reboot lại toàn bộ thiết bị Jetson.
  - Phải dùng lệnh `docker exec -it <container> bash` chui vào terminal container để gõ lệnh chạy thủ công.
  - Thời gian chờ Jetson khởi động lại lâu (1–2 phút), gây gián đoạn quy trình thử nghiệm.
* **Mục tiêu cải tiến:**
  - **Giai đoạn 1 (Hiện tại - Đang cắm màn hình Jetson test):** Khởi động lại toàn bộ pipeline/agent bằng **đúng 1 file script** hoặc 1 click đúp trên màn hình Jetson, giải phóng VRAM an toàn trong 2–3 giây.
  - **Giai đoạn 2 (Dài hạn - Triển khai thực địa):** Điều khiển từ xa hoàn toàn qua **WebGIS / MQTT (Zero-touch)**, không cần đụng vào thiết bị Jetson.

---

## 2. Phương án 1 (Đã triển khai): 1-Click Script trên Host Jetson

### 2.1. Cơ chế hoạt động
File thực thi: `restart_edge.sh` (nằm ở thư mục gốc project).
Quy trình thực hiện tự động:
1. **Nhận diện Docker container:** Tự động dò tìm container đang chạy DeepStream / Jetson AI.
2. **Graceful Shutdown (Giải phóng tài nguyên):** Gửi tín hiệu `SIGINT` (Ctrl+C) vào tiến trình `main.py` để GStreamer gửi sự kiện EOS (End-Of-Stream), cho phép TensorRT giải phóng bộ nhớ VRAM và nhả cảm biến CSI Camera.
3. **Dọn dẹp triệt để:** Nếu tiến trình còn ngậm bộ nhớ, tự động gửi `SIGTERM` / `SIGKILL`.
4. **Khởi động nền:** Chạy lại `communication/jetson_agent.py` dưới dạng tiến trình nền (`docker exec -d`) bên trong container mà không cần mở interactive shell.

### 2.2. Hướng dẫn sử dụng
* **Cách 1: Chạy qua Terminal:**
  ```bash
  # Cấp quyền thực thi (chỉ cần làm 1 lần)
  chmod +x restart_edge.sh

  # Chạy khởi động lại pipeline
  ./restart_edge.sh

  # Nếu camera CSI bị đơ hoặc báo "Device busy", thêm cờ reset driver:
  ./restart_edge.sh --reset-camera
  ```

* **Cách 2: Click đúp từ màn hình Desktop Jetson (GUI):**
  - Đã tạo sẵn file shortcut: `tools/Restart_Pipeline.desktop`.
  - Copy file này ra màn hình Desktop của Jetson:
    ```bash
    cp tools/Restart_Pipeline.desktop ~/Desktop/
    chmod +x ~/Desktop/Restart_Pipeline.desktop
    ```
  - Sau đó chỉ cần click đúp vào biểu tượng trên Desktop để khởi động lại.

---

## 3. Phương án 2 (Định hướng tương lai): Điều khiển & Khởi động từ xa qua WebGIS / MQTT

Khi thiết bị Jetson được lắp đặt thực tế trên cột đèn giao thông hoặc hộp kỹ thuật ngoài trời, người bảo trì không thể cắm màn hình hay bàn phím. Phương án 2 cho phép **toàn quyền kiểm soát từ xa**.

```
┌────────────────────────┐         MQTT TLS         ┌─────────────────────────┐
│     WebGIS Frontend    │ ───────────────────────> │      MQTT Broker        │
│  [Nút: Restart/Start]  │                          │    (HiveMQ Cloud)       │
└────────────────────────┘                          └────────────┬────────────┘
            ▲                                                    │
            │ HTTP / WebSocket                                   │ Topic: traffic/{id}/command
            │                                                    ▼
┌────────────────────────┐                          ┌─────────────────────────┐
│     FastAPI Backend    │                          │      Jetson Agent       │
│  (Quản trị luồng lệnh) │                          │  (Chạy vĩnh viễn nền)   │
└────────────────────────┘                          └────────────┬────────────┘
                                                                 │ subprocess.Popen
                                                                 ▼
                                                    ┌─────────────────────────┐
                                                    │ Pipeline Worker main.py │
                                                    │ (AI / TensorRT Engine)  │
                                                    └─────────────────────────┘
```

### 3.1. Các lệnh điều khiển sẵn có qua MQTT
| Action | Ý nghĩa | Payload mẫu |
| :--- | :--- | :--- |
| `start_pipeline` | Khởi động phân tích AI với nguồn video/CSI và ROI mới | `{"action": "start_pipeline", "params": {"source_type": "csi", "roi_config": "remote"}}` |
| `stop_pipeline` | Dừng phân tích an toàn, nhả VRAM | `{"action": "stop_pipeline"}` |
| `restart_analytics` | Tự động stop và start lại pipeline | `{"action": "restart_analytics"}` |
| `reload_config` | Nạp lại tọa độ ROI mới mà không cần tắt pipeline | `{"action": "reload_config"}` |
| `capture_preview` | Chụp 1 frame gửi về WebGIS để người dùng vẽ ROI | `{"action": "capture_preview"}` |
| `fetch_logs` | Lấy 100 dòng log mới nhất gửi về WebGIS phân tích | `{"action": "fetch_logs", "params": {"lines": 100}}` |

### 3.2. Những việc cần làm để hoàn thiện Phương án 2
1. **WebGIS UI:** Thêm cụm nút điều khiển trên thanh công cụ chi tiết của Camera/Nút giao:
   - `[ Khởi động lại AI ]`
   - `[ Dừng khẩn cấp ]`
   - `[ Nạp lại cấu hình ROI ]`
2. **Backend API:** Thêm endpoint:
   - `POST /api/v1/edge/{edge_id}/restart` -> publish lệnh `restart_analytics` lên topic MQTT tương ứng.
3. **Cơ chế Watchdog:** Nếu Agent bị mất kết nối MQTT quá 3 phút, tự động kích hoạt chế độ chạy offline an toàn.

---

## 4. Lộ trình cải tiến & Thay thế trong tương lai (Future Backlog)

Dưới đây là các hạng mục kỹ thuật cần tiếp tục tối ưu hóa khi hệ thống phát triển quy mô:

### 4.1. Tự phục hồi phần cứng (Auto-Healing & Watchdog)
* **Vấn đề:** Camera CSI trên Jetson Nano thỉnh thoảng bị timeout (`nvarguscamerasrc` crash do sụt áp nguồn hoặc nhiễu dây cáp ribbon).
* **Giải pháp:**
  - Viết 1 tiến trình giám sát nội bộ (Health Watchdog): nếu 10 giây liên tục không nhận được frame mới từ camera, tự động gọi `sudo systemctl restart nvargus-daemon` và khởi động lại pipeline.

### 4.2. Cập nhật mã nguồn từ xa (OTA - Over-The-Air Update)
* **Vấn đề:** Khi có tính năng mới hoặc vá lỗi thuật toán, việc sao chép file thủ công sang Jetson tốn thời gian.
* **Giải pháp:**
  - Bổ sung lệnh MQTT `git_pull_update`: Jetson nhận lệnh sẽ tự động `git pull origin main`, kiểm tra cú pháp và khởi động lại pipeline.
  - Sử dụng Docker Registry riêng (Docker Hub / GitHub Container Registry) kết hợp với **Watchtower** để tự động kéo image mới khi có bản cập nhật.

### 4.3. Tối ưu hóa mô hình & Tiết kiệm VRAM trên Jetson Nano
* **Hiện trạng:** Jetson Nano chỉ có 4GB RAM dùng chung (Unified Memory giữa CPU và GPU). Pipeline dễ chạm ngưỡng 3.8GB gây tràn RAM (OOM-killer).
* **Giải pháp thay thế:**
  - Chuyển đổi mô hình YOLO sang chuẩn **TensorRT FP16** hoặc **INT8 Calibrated** (giảm 50% dung lượng VRAM, tăng FPS từ 12-15 lên 25-30 FPS).
  - Tích hợp bộ giải phóng Swap file tự động (tối thiểu 4GB-8GB ZRAM trên SSD/eMMC).

### 4.4. Live Stream hình ảnh thời gian thực lên WebGIS
* **Hiện trạng:** Hệ thống gửi dữ liệu telemetry (số lượng xe, vận tốc, chỉ số kẹt xe) dạng JSON qua MQTT và snapshot ảnh định kỳ.
* **Định hướng mở rộng:**
  - Tích hợp máy chủ **WebRTC / RTSP-to-HLS** (ví dụ MediaMTX) để khi người vận hành trên WebGIS bấm vào camera có thể xem video trực tiếp độ trễ cực thấp (< 0.5s).

---

## 5. Bảng checklist theo dõi tiến độ

- [x] **Phương án 1:** Tạo script `restart_edge.sh` 1-click dừng an toàn và nạp lại code trong Docker.
- [x] **Phương án 1:** Tạo file desktop launcher `tools/Restart_Pipeline.desktop` cho màn hình Jetson GUI.
- [ ] **Phương án 2:** Thiết kế nút bấm `Restart Pipeline` trên giao diện WebGIS Operations Center.
- [ ] **Phương án 2:** Viết API Backend FastAPI kích hoạt lệnh MQTT `restart_analytics`.
- [ ] **Cải tiến 4.1:** Tích hợp auto-heal cho CSI Camera `nvargus-daemon`.
- [ ] **Cải tiến 4.2:** Thiết lập cơ chế cập nhật mã nguồn OTA tự động.
- [ ] **Cải tiến 4.3:** Đo kiểm benchmark mô hình TensorRT FP16 / INT8 để giải phóng thêm VRAM.
