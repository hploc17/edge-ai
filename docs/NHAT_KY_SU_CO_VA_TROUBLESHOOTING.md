# NHẬT KÝ SỰ CỐ VÀ HƯỚNG DẪN TROUBLESHOOTING
> **Tài liệu lưu vết lỗi kỹ thuật, nguyên nhân gốc rễ và bài học phòng ngừa**  
> *Hệ thống Giám sát Giao thông Thông minh Edge AI (NVIDIA Jetson) & WebGIS*  
> *Cập nhật lần cuối: 26/10/2026*

---

## 📌 QUY TẮC VÀNG TRƯỚC KHI CẬP NHẬT HOẶC SỬA CODE
Trước khi sửa bất kỳ file nào trong dự án, hãy đọc qua checklist sau:
1. **Không dùng chung `MQTT Client ID`:** Mỗi tiến trình (WebGIS Backend, Jetson Agent, Pipeline, Tool Diagnostic) **BẮT BUỘC** phải có Client ID riêng biệt, nếu trùng sẽ bị Broker đá văng (`rc=7`).
2. **Luôn giải phóng Camera CSI và VRAM bằng `SIGINT`:** Không dùng `kill -9` ngay lập tức vì sẽ làm treo daemon phần cứng `nvargus-daemon`.
3. **Kiểm tra biến trước khi truy cập phần tử mảng:** Tránh lỗi `NameError` hoặc `IndexError` trong các hàm callback xử lý tin nhắn MQTT.
4. **Kiểm tra nguồn dữ liệu:** Nếu chạy bằng file video, video phát hết là pipeline sẽ tự dừng (`End of stream`).

---

## 📋 DANH SÁCH CÁC SỰ CỐ ĐÃ GẶP VÀ CÁCH KHẮC PHỤC

---

### Sự cố 1: WebGIS hiển thị `OFFLINE` dù Jetson đang chạy và gửi nhịp tim liên tục
* **Mức độ:** 🔴 Nghiêm trọng (Gây mất đồng bộ toàn bộ hệ thống).
* **Vị trí lỗi:** `webgis/backend/services/mqtt_service.py` trong hàm `_on_message()`.
* **Hiện tượng:** 
  - Jetson Agent đã chạy nền, gửi bản tin `traffic/edge-01/heartbeat` mỗi 5 giây.
  - Nhưng trên màn hình WebGIS, nút giao thông vẫn màu xám và hiện `OFFLINE`.
* **Nguyên nhân gốc rễ (Root Cause):**
  Trong hàm nhận tin nhắn `_on_message()`, lập trình viên gọi kiểm tra:
  ```python
  if topic == "traffic/discovery/announce" or (len(parts) >= 3 and parts[2] == "announce"):
  ```
  nhưng biến `parts = topic.split('/')` **chưa hề được định nghĩa trước đó**.
  Khi nhận bất kỳ gói tin nào từ Jetson, Python quăng lỗi `NameError: name 'parts' is not defined` và nhảy vào khối `except`, khiến **toàn bộ dữ liệu của Jetson bị Backend vứt bỏ âm thầm**.
* **Cách khắc phục:**
  Khai báo ngay dòng đầu của hàm nhận tin:
  ```python
  topic = msg.topic
  parts = topic.split('/') # <- Bổ sung dòng này
  payload = json.loads(msg.payload.decode("utf-8"))
  ```
* **Bài học phòng ngừa:** Khi xử lý MQTT routing theo topic cấp bậc (`traffic/+/+`), luôn tách `topic.split('/')` ngay từ đầu hàm.

---

### Sự cố 2: Chạy script restart trên Jetson nhưng không có dữ liệu xe (Telemetry)
* **Mức độ:** 🟡 Trung bình.
* **Vị trí lỗi:** `restart_edge.sh` và `communication/jetson_agent.py`.
* **Hiện tượng:** Chạy file `restart_edge.sh` thấy báo thành công, nhưng chỉ có nhịp tim, không thấy số lượng xe, vận tốc và ảnh chụp snapshot.
* **Nguyên nhân gốc rễ:**
  Hệ thống thiết kế theo kiến trúc 2 tầng:
  - **Tầng 1 (Jetson Agent):** Chỉ là tiến trình daemon nhận lệnh MQTT và bắn nhịp tim.
  - **Tầng 2 (Pipeline Worker `main.py`):** Mới là nơi chạy mô hình AI, TensorRT và đếm xe.
  Script cũ chỉ bật Tầng 1 mà không tự kích hoạt Tầng 2.
* **Cách khắc phục:**
  Thêm cấu hình `AUTO_START_PIPELINE=true` trong `jetson_agent.py`. Khi Agent khởi động, nó sẽ tự động kích hoạt tiến trình con `main.py`.
* **Bài học phòng ngừa:** Khi khởi động lại hệ thống Edge, luôn kiểm tra xem cả tiến trình Agent và tiến trình Pipeline Worker đều đang có mã PID chạy trong Docker (`docker top`).

---

### Sự cố 3: Pipeline AI chạy được ~25-30 giây rồi đột ngột tắt
* **Mức độ:** 🟡 Phổ biến khi thử nghiệm.
* **Vị trí:** Log `pipeline.log` hiển thị `[PIPELINE] End of stream` và `[NvMultiObjectTracker] De-initialized`.
* **Hiện tượng:** Hệ thống vừa bật lên chạy rất mượt (~19 FPS), nhưng sau nửa phút thì dừng hẳn, WebGIS sau 25 giây tự chuyển sang `OFFLINE`.
* **Nguyên nhân gốc rễ:**
  Tham số nguồn đang là file video (`--source Video/traffic.mp4`). Khi GStreamer đọc đến frame cuối cùng của video, nó phát tín hiệu EOS (End Of Stream) và tự động thoát chương trình.
* **Cách khắc phục:**
  - Nếu test video: Bật chế độ phát lặp vô tận (Looping) hoặc chạy lại pipeline.
  - Khi triển khai thực tế: Đổi nguồn sang camera phần cứng `--source csi` (camera quay 24/7 không có điểm dừng).
* **Bài học phòng ngừa:** Luôn phân biệt giữa việc "hệ thống bị crash" và "hệ thống hoàn thành phát hết video mẫu".

---

### Sự cố 4: Xung đột Camera CSI trên Jetson (`nvarguscamerasrc: Resource busy`)
* **Mức độ:** 🔴 Nghiêm trọng (Thường khiến người dùng phải reboot máy).
* **Hiện tượng:** Khởi động lại pipeline thì màn hình đen xì hoặc log báo `Error: Camera device is busy` / `Failed to initialize nvarguscamerasrc`.
* **Nguyên nhân gốc rễ:**
  Tiến trình cũ bị tắt bằng `kill -9` đột ngột. Trình điều khiển camera CSI phần cứng của NVIDIA Jetson chưa kịp nhận tín hiệu nhả thiết bị (EOS) nên daemon `nvargus-daemon` của hệ điều hành vẫn giữ khóa độc quyền cảm biến.
* **Cách khắc phục:**
  1. Luôn dùng tín hiệu dừng an toàn `SIGINT` (Ctrl+C):
     ```bash
     pkill -INT -f "python3.*main"
     ```
  2. Nếu camera đã bị kẹt, **KHÔNG CẦN REBOOT JETSON**, chỉ cần khởi động lại daemon camera:
     ```bash
     sudo systemctl restart nvargus-daemon
     # hoặc chạy: ./restart_edge.sh --reset-camera
     ```
* **Bài học phòng ngừa:** Không bao giờ ép dừng (`SIGKILL`) camera CSI trừ khi đã thử `SIGINT` thất bại sau 5 giây.

---

### Sự cố 5: Mất kết nối MQTT liên tục với mã lỗi `rc=7` (`MQTT_ERR_CONN_LOST`)
* **Mức độ:** 🟡 Trung bình.
* **Hiện tượng:** Log Jetson hiển thị liên tục:
  `[MQTT] Disconnected for edge-01 (rc=7), reconnecting...`
* **Nguyên nhân gốc rễ:**
  Hai hoặc nhiều tiến trình kết nối vào HiveMQ Cloud dùng **chung một Client ID** (ví dụ: máy tính PC test cũng dùng `edge-01`, Jetson cũng dùng `edge-01`). Broker MQTT quy định khi một client mới đăng nhập với cùng ID, client cũ sẽ bị đá văng ngay lập tức.
* **Cách khắc phục:**
  1. Đặt Client ID CỐ ĐỊNH phân tách rõ ràng (tuyệt đối không để trùng nhau hay tự sinh ngẫu nhiên):
     - `MQTT_AGENT_CLIENT_ID=edge-01-agent` (cho Jetson Agent)
     - `MQTT_PIPELINE_CLIENT_ID=edge-01-pipeline` (cho Pipeline AI worker)
     - `MQTT_SNAPSHOT_CLIENT_ID=edge-01-snapshot` (cho Dịch vụ chụp ảnh)
     - `MQTT_MAINT_CLIENT_ID=edge-01-maint` (cho Công cụ chẩn đoán lấy log)
     - `WEBGIS_MQTT_CLIENT_ID=webgis-backend-hub` (cho WebGIS Backend Hub)
  2. Trong [main.py](file:///d:/edge-ai-web/main.py#L559), truyền tường minh `client_id` khi khởi tạo:
     ```python
     pipeline_client_id = os.getenv('MQTT_PIPELINE_CLIENT_ID', '%s-pipeline' % os.getenv('EDGE_ID', 'edge-01'))
     mqtt_publisher = MQTTPublisher(command_callback=None, client_id=pipeline_client_id)
     ```
  3. Trong [mqtt_client.py](file:///d:/edge-ai-web/communication/mqtt_client.py), khi `main.py` dừng (`stop()`), chỉ ngắt kết nối worker, KHÔNG phát bản tin `status: "offline"` (chỉ duy nhất Jetson Agent mới đại diện cho trạng thái nguồn của thiết bị).
* **Bài học phòng ngừa:** Quản lý vòng đời dịch vụ qua `sudo systemctl restart <service>` hoặc `docker restart <container>` để hệ thống tự dọn dẹp sạch sẽ 100% tài nguyên cũ.

---

### Sự cố 6: Lỗi thiếu thư viện khi chạy tool độc lập (`NameError: name 'mqtt_lib' is not defined`)
* **Mức độ:** 🟢 Nhẹ.
* **Vị trí:** `tools/fetch_jetson_logs.py`.
* **Hiện tượng:** Chạy tool lấy log báo lỗi `NameError: name 'mqtt_lib' is not defined`.
* **Nguyên nhân gốc rễ:** Trong code có gọi `mqtt_lib.Client()` nhưng ở đầu file quên lệnh `import paho.mqtt.client as mqtt_lib`.
* **Cách khắc phục:** Bổ sung import đầy đủ và bọc `try...except ImportError` an toàn.

---

## 🛠️ TỔNG HỢP CÁC LỆNH CỨU HỘ NHANH TRÊN JETSON

| Tình huống | Lệnh thực thi nhanh |
| :--- | :--- |
| **Khởi động lại toàn bộ pipeline bằng 1 click** | `./restart_edge.sh` |
| **Khởi động lại và reset cảm biến Camera CSI** | `./restart_edge.sh --reset-camera` |
| **Xem các tiến trình Python đang chạy ngầm** | `ps -eo pid,%cpu,%mem,cmd \| grep python` |
| **Xem tiến trình chạy bên trong Docker từ ngoài host** | `docker top <tên_container>` |
| **Dừng khẩn cấp toàn bộ tiến trình AI** | `pkill -INT -f "python3.*main"` |
| **Khởi động lại driver Camera CSI khi bị đơ** | `sudo systemctl restart nvargus-daemon` |
| **Theo dõi log phân tích trực tiếp** | `tail -f pipeline.log` |
| **Lấy log từ Jetson về PC qua MQTT** | `python tools/fetch_jetson_logs.py --edge-id edge-01` |
