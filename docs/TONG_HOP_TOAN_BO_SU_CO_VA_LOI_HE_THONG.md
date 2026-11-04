# TỔNG HỢP TOÀN BỘ SỰ CỐ, LỖI KỸ THUẬT VÀ GIẢI PHÁP KHẮC PHỤC
> **Dự án:** Hệ thống Giám sát Giao thông Thông minh Đa tầng (Edge AI Jetson Nano & WebGIS Điều hành Trung tâm)  
> **Phạm vi rà soát:** Toàn bộ lịch sử trao đổi, nhật ký lỗi thực tế từ giai đoạn khởi tạo (Tháng 07/2026) đến giai đoạn hoàn thiện & triển khai thực địa (Tháng 10/2026).  
> **Mục đích:** Lưu vết 100% các vấn đề kỹ thuật thực tế đã gặp, nguyên nhân gốc rễ (Root Cause), giải pháp đã áp dụng và quy tắc phòng ngừa triệt để khi vận hành, bảo trì hoặc bảo vệ đồ án/khoá luận trước hội đồng.

---

## 📑 MỤC LỤC TỔNG QUAN

1. [Bảng Ma Trận Tổng Hợp Nhanh Sự Cố](#-bảng-ma-trận-tổng-hợp-nhanh-sự-cố)
2. [Nhóm 1: Hạ Tầng Phần Cứng Jetson, Linux, Docker & Trình Biên Dịch](#-nhóm-1-hạ-tầng-phần-cứng-jetson-linux-docker--trình-biên-dịch)
3. [Nhóm 2: Pipeline DeepStream, GStreamer & Camera CSI](#-nhóm-2-pipeline-deepstream-gstreamer--camera-csi)
4. [Nhóm 3: Thuật Toán AI, Tracker, Ma Trận Homography & Logic Đếm Xe](#-nhóm-3-thuật-toán-ai-tracker-ma-trận-homography--logic-đếm-xe)
5. [Nhóm 4: Giao Tiếp Mạng IoT, MQTT HiveMQ Cloud & Đồng Bộ Trạng Thái](#-nhóm-4-giao-tiếp-mạng-iot-mqtt-hivemq-cloud--đồng-bộ-trạng-thái)
6. [Nhóm 5: Streaming Video Trực Tiếp MediaMTX (RTSP, WebRTC, WHEP)](#-nhóm-5-streaming-video-trực-tiếp-mediamtx-rtsp-webrtc-whep)
7. [Nhóm 6: WebGIS Backend (FastAPI, SQLite, Schema & Environment)](#-nhóm-6-webgis-backend-fastapi-sqlite-schema--environment)
8. [Nhóm 7: WebGIS Frontend (React, Vite, MapLibre GL & Giao Diện Điều Hành)](#-nhóm-7-webgis-frontend-react-vite-maplibre-gl--giao-diện-điều-hành)
9. [Nhóm 8: Điều Khiển Từ Xa, Chụp Ảnh Snapshot & Bộ Nhớ Đệm Ngoại Tuyến (Outbox)](#-nhóm-8-điều-khiển-từ-xa-chụp-ảnh-snapshot--bộ-nhớ-đệm-ngoại-tuyến-outbox)
10. [Checklist Vàng 10 Bước Trước Khi Chỉnh Sửa Hoặc Triển Khai](#-checklist-vàng-10-bước-trước-khi-chỉnh-sửa-hoặc-triển-khai)

---

## 📊 BẢNG MA TRẬN TỔNG HỢP NHANH SỰ CỐ

| STT | Mã Sự Cố | Vị Trí / Thành Phần | Triệu Chứng / Lỗi Nổi Bật | Mức Độ | Trạng Thái |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **01** | `ERR-HW-01` | Docker Socket | `Got permission denied while trying to connect to Docker daemon` | 🟡 Trung bình | Đã giải quyết |
| **02** | `ERR-HW-02` | Build Docker | `In file included from util.cpp: fatal error: NvInfer.h: No such file` | 🔴 Nghiêm trọng | Đã giải quyết |
| **03** | `ERR-HW-03` | Python pip aarch64 | `Failed to determine system's GEOS version: Could not find geos-config` | 🟡 Trung bình | Đã giải quyết |
| **04** | `ERR-HW-04` | Camera Ribbon I2C | `imx219 7-0010: error during i2c read probe (-121)` | 🔴 Nghiêm trọng | Đã giải quyết |
| **05** | `ERR-HW-05` | Camera CSI Daemon | `Connecting to nvargus-daemon failed: No such file or directory` | 🔴 Nghiêm trọng | Đã giải quyết |
| **06** | `ERR-HW-06` | Headless Jetson X11 | `gst_parse_error: no element "ximagesink" / Gdk-ERROR BadAlloc` | 🟡 Trung bình | Đã giải quyết |
| **07** | `ERR-HW-07` | Docker Desktop PC | `Failed to connect to docker API at npipe:////./pipe/dockerDesktop...` | 🟢 Nhẹ | Đã giải quyết |
| **08** | `ERR-PIPE-01` | GStreamer URI | `[!] GStreamer Error: Invalid URI "Video/test.mp4"` | 🟡 Trung bình | Đã giải quyết |
| **09** | `ERR-PIPE-02` | Custom Yolo Parser | `Could not open lib: libnvdsinfer_custom_impl_Yolo.so: No such file` | 🔴 Nghiêm trọng | Đã giải quyết |
| **10** | `ERR-PIPE-03` | TensorRT Engine | `Deserialize engine failed because file path: exp.engine open error` | 🔴 Nghiêm trọng | Đã giải quyết |
| **11** | `ERR-PIPE-04` | CLI Arguments | `app_custom.py: error: unrecognized arguments: --sourve csi` | 🟢 Nhẹ | Đã giải quyết |
| **12** | `ERR-PIPE-05` | Video End of Stream | Pipeline tự thoát sau 25-30 giây (`End of stream`, De-initialized) | 🟡 Trung bình | Đã giải quyết |
| **13** | `ERR-PIPE-06` | PyDS API Binding | `AttributeError: 'pyds.NvOSD_TextParams' has no attribute 'set_font_size'` | 🟡 Trung bình | Đã giải quyết |
| **14** | `ERR-PIPE-07` | GStreamer Surface | `Input buffer number of surfaces (0) must be equal to mux` | 🔴 Nghiêm trọng | Đã giải quyết |
| **15** | `ERR-AI-01` | YOLO Class Labels | `Vehicle classes missing from labels: o_to, xe_buyt, xe_may, xe_tai` | 🔴 Nghiêm trọng | Đã giải quyết |
| **16** | `ERR-AI-02` | Homography Projection | Vận tốc tính ra số âm hoặc vọt lên bất thường (>200 km/h, 0.08 km/h) | 🔴 Nghiêm trọng | Đã giải quyết |
| **17** | `ERR-AI-03` | ByteTrack ID Switch | Đếm xe bị nhảy số liên tục, mất track khi phương tiện che khuất | 🟡 Trung bình | Đã giải quyết |
| **18** | `ERR-AI-04` | Congestion Scoring | Báo kẹt xe ảo tại ngã tư có đèn đỏ khi xe dừng bình thường | 🟡 Trung bình | Đã giải quyết |
| **19** | `ERR-AI-05` | ROI File Encoding | `ERROR: Khong the luu roi.json: 'ascii' codec can't encode characters` | 🟡 Trung bình | Đã giải quyết |
| **20** | `ERR-NET-01` | MQTT Broker HiveMQ | `[MQTT] Disconnected for edge-01 (rc=7), reconnecting...` | 🔴 Nghiêm trọng | Đã giải quyết |
| **21** | `ERR-NET-02` | MQTT Firewall/DNS | `[MQTT] Connection failed: [Errno 113] No route to host` | 🔴 Nghiêm trọng | Đã giải quyết |
| **22** | `ERR-NET-03` | MQTT Backend Dispatch | `NameError: name 'parts' is not defined` nuốt chửng bản tin Jetson | 🔴 Nghiêm trọng | Đã giải quyết |
| **23** | `ERR-NET-04` | LWT Offline Giả | Dừng `main.py` làm WebGIS báo thiết bị sập nguồn (offline giả) | 🔴 Nghiêm trọng | Đã giải quyết |
| **24** | `ERR-NET-05` | MQTT Asyncio Thread | `Error processing MQTT message: There is no current event loop in thread` | 🟡 Trung bình | Đã giải quyết |
| **25** | `ERR-NET-06` | Edge ID Mismatch | Backend gửi lệnh tới `traffic/edge-01`, Jetson nghe `edge-02` | 🔴 Nghiêm trọng | Đã giải quyết |
| **26** | `ERR-STR-01` | RTSP Client Sink | `GstRTSPClientSink: Could not open resource for writing` | 🔴 Nghiêm trọng | Đã giải quyết |
| **27** | `ERR-STR-02` | Hardware Encoder | `WARNING: could not set property "profile" on "nvv4l2h264enc"` | 🟡 Trung bình | Đã giải quyết |
| **28** | `ERR-STR-03` | Xung Đột Camera CSI | Vừa stream live vừa gọi `capture_preview` làm treo cứng cảm biến | 🔴 Nghiêm trọng | Đã giải quyết |
| **29** | `ERR-STR-04` | WebRTC / WHEP Port | Video player đen màn hình, WebRTC time out do Firewall Windows | 🟡 Trung bình | Đã giải quyết |
| **30** | `ERR-BE-01` | Port 8000 Conflict | `[Errno 10048] error while attempting to bind on address ('0.0.0.0', 8000)` | 🟡 Trung bình | Đã giải quyết |
| **31** | `ERR-BE-02` | WinError 10013 | `[WinError 10013] An attempt was made to access a socket in a way forbidden` | 🟡 Trung bình | Đã giải quyết |
| **32** | `ERR-BE-03` | SQLite Schema Drift | `SQLite check_offline_cameras error: no such column: last_heartbeat` | 🟡 Trung bình | Đã giải quyết |
| **33** | `ERR-BE-04` | Circular Import Config| `ModuleNotFoundError: No module named 'config.settings'; 'config' is not...`| 🟡 Trung bình | Đã giải quyết |
| **34** | `ERR-BE-05` | Phân Mảnh Biến .env | Cấu hình backend, frontend, jetson trỏ nhiều file .env khác nhau | 🟡 Trung bình | Đã giải quyết |
| **35** | `ERR-FE-01` | React Hooks Order | `React has detected a change in the order of Hooks called by Drawer` | 🔴 Nghiêm trọng | Đã giải quyết |
| **36** | `ERR-FE-02` | Reference / Null Type | `Uncaught TypeError: Cannot read properties of undefined ('toLowerCase')` | 🟡 Trung bình | Đã giải quyết |
| **37** | `ERR-FE-03` | MapLibre Style Race | Heatmap không vẽ được vì addSource/addLayer trước khi style load | 🔴 Nghiêm trọng | Đã giải quyết |
| **38** | `ERR-FE-04` | GeoJSON Inversion | Tọa độ điểm bị đảo lộn giữa Leaflet `[lat, lng]` và MapLibre `[lng, lat]` | 🟡 Trung bình | Đã giải quyết |
| **39** | `ERR-FE-05` | WebSocket Loop Crash | `WebSocket connection to 'ws://localhost:3000/ws' failed` lặp vô tận | 🟡 Trung bình | Đã giải quyết |
| **40** | `ERR-CMD-01` | Frame Unbound Local | `Handler error for capture_preview: local variable 'frame' referenced before`| 🔴 Nghiêm trọng | Đã giải quyết |
| **41** | `ERR-CMD-02` | Missing NumPy Import | `Handler error for capture_preview: name 'np' is not defined` | 🟢 Nhẹ | Đã giải quyết |
| **42** | `ERR-CMD-03` | Zombie Subprocess | Bấm Stop trên WebGIS nhưng Jetson không nhả camera, process vẫn chạy | 🔴 Nghiêm trọng | Đã giải quyết |
| **43** | `ERR-CMD-04` | Offline Outbox Hang | `Upload pending (ValueError); JPEG retained` treo chu kỳ gửi lại | 🟡 Trung bình | Đã giải quyết |

---

## 🛠️ CHI TIẾT TỪNG SỰ CỐ THEO NHÓM

---

### 🧩 NHÓM 1: HẠ TẦNG PHẦN CỨNG JETSON, LINUX, DOCKER & TRÌNH BIÊN DỊCH

#### 1. Sự cố `ERR-HW-01`: Docker Socket Permission Denied
* **Hiện tượng:** Chạy `docker build` hoặc `docker run` trên Jetson Nano báo lỗi:
  ```text
  Got permission denied while trying to connect to the Docker daemon socket at unix:///var/run/docker.sock
  ```
* **Nguyên nhân:** User hiện tại (`admin1`) chưa được thêm vào nhóm quyền `docker`.
* **Khắc phục:**
  ```bash
  sudo usermod -aG docker $USER
  newgrp docker
  ```

#### 2. Sự cố `ERR-HW-02`: Thiếu Header TensorRT khi Compile Custom Parser YOLO
* **Hiện tượng:** Build Dockerfile DeepStream đến bước biên dịch `libnvdsinfer_custom_impl_Yolo.so` bị dừng:
  ```text
  In file included from util.cpp:26:0:
  utils.h:36:10: fatal error: NvInfer.h: No such file or directory
  #include "NvInfer.h"
  ```
* **Nguyên nhân:** Đường dẫn include của CUDA/TensorRT trong Makefile trỏ sai hoặc container nền `deepstream-l4t:6.0.1-samples` thiếu biến môi trường `CUDA_VER=10.2` trên nền JetPack 4.6.1.
* **Khắc phục:** Thiết lập tường minh biến trong Makefile hoặc lệnh build:
  ```bash
  CUDA_VER=10.2 make -C /opt/nvidia/deepstream/deepstream-6.0/sources/DeepStream-Yolo
  ```

#### 3. Sự cố `ERR-HW-03`: Lỗi biên dịch thư viện hình học Shapely từ Source
* **Hiện tượng:** Chạy `pip3 install shapely` trong môi trường Jetson Python 3.6/3.8:
  ```text
  WARNING: Failed to determine system's GEOS version: Could not find geos-config
  OSError: Could not find library geos_c or load any of its variants
  ```
* **Nguyên nhân:** Shapely cần thư viện C nền tảng GEOS để tính toán đa giác (Polygon/ROI Intersection).
* **Khắc phục:** Cài đặt gói phát triển hệ thống trước khi cài python package:
  ```bash
  sudo apt-get update && sudo apt-get install -y libgeos-dev
  pip3 install shapely==1.8.5.post1
  ```

#### 4. Sự cố `ERR-HW-04`: Cảm biến Camera CSI IMX219 lỏng cáp phần cứng (I2C Probe Fail)
* **Hiện tượng:** Kernel dmesg thông báo:
  ```text
  [ 1.360925] imx219 7-0010: imx219_board_setup: error during i2c read probe (-121)
  imx219 7-0010: Device is not found
  ```
* **Nguyên nhân:** Cáp dẹt (ribbon cable) của camera Raspberry Pi Camera v2 (IMX219) cắm ngược mặt tiếp xúc, bị lỏng hoặc chốt khóa trên cổng J13 của Jetson Nano chưa được cài chặt.
* **Khắc phục:** Tắt nguồn Jetson, cắm lại cáp ribbon sao cho mặt tiếp xúc kim loại hướng về phía chip vi xử lý (hướng vào trong board), gài chặt ngàm khóa, khởi động lại.

#### 5. Sự cố `ERR-HW-05`: Treo Trình Điều Khiển Phần Cứng `nvargus-daemon`
* **Hiện tượng:** Khi chạy lại pipeline, GStreamer văng lỗi:
  ```text
  (Argus) Error FileOperationFailed: Connecting to nvargus-daemon failed: No such file or directory
  Error: Camera device is busy / Failed to initialize nvarguscamerasrc
  ```
* **Nguyên nhân:** Tiến trình trước đó bị tắt cưỡng bức bằng `kill -9` (`SIGKILL`). Trình điều khiển camera CSI chưa kịp gọi hàm `deinit()`, khiến daemon cấp thấp giữ khóa độc quyền cảm biến.
* **Khắc phục:** Khởi động lại daemon mà không cần reboot cả máy:
  ```bash
  sudo systemctl restart nvargus-daemon
  ```

#### 6. Sự cố `ERR-HW-06`: Lỗi hiển thị X11 trên Jetson Headless (Không cắm màn hình)
* **Hiện tượng:** Khởi chạy pipeline AI ném lỗi:
  ```text
  [!] Lỗi khi mở màn hình X11 (gst_parse_error: no element "ximagesink" (1))
  Gdk-ERROR **: The program received an X Window System error (BadAlloc)
  ```
* **Nguyên nhân:** Jetson Nano hoạt động độc lập (không cắm cáp HDMI/DisplayPort). Mã nguồn pipeline lại cấu hình phần tử sink là `autovideosink` hoặc `nveglglessink` cố vẽ cửa sổ đồ họa X11.
* **Khắc phục:** Tách cấu hình linh hoạt: Nếu phát hiện không có biến môi trường `DISPLAY` hoặc cờ `--headless`, tự động chuyển sink sang `fakesink` hoặc `rtspclientsink`.

#### 7. Sự cố `ERR-HW-07`: Docker Daemon không chạy trên Windows host
* **Hiện tượng:** Khi chạy các tool test Docker trên PC:
  ```text
  failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine
  ```
* **Nguyên nhân:** Ứng dụng Docker Desktop trên Windows chưa được khởi động.
* **Khắc phục:** Bật Docker Desktop trước khi thực hiện các script đóng gói container.

---

### 🎥 NHÓM 2: PIPELINE DEEPSTREAM, GSTREAMER & CAMERA CSI

#### 8. Sự cố `ERR-PIPE-01`: Định Dạng URI Không Hợp Lệ trong GStreamer
* **Hiện tượng:**
  ```text
  [!] GStreamer Error: gst-resource-error-quark: Invalid URI "Video/test.mp4". (3) | gsturidecodebin.c
  ```
* **Nguyên nhân:** Phần tử `uridecodebin` trong GStreamer chuẩn quy định URI phải bắt đầu bằng scheme chuẩn `file:///` hoặc `rtsp://`, không chấp nhận đường dẫn tương đối trực tiếp.
* **Khắc phục:** Chuẩn hóa đường dẫn trước khi đưa vào pipeline string:
  ```python
  if not source.startswith(("file://", "rtsp://", "http://")):
      abs_path = os.path.abspath(source)
      source_uri = f"file://{abs_path}"
  ```

#### 9. Sự cố `ERR-PIPE-02`: Thiếu Thư Viện Custom Bounding Box Parser Của YOLO
* **Hiện tượng:**
  ```text
  ERROR: Could not open lib: /opt/nvidia/deepstream/deepstream-6.0/sources/DeepStream-Yolo/libnvdsinfer_custom_impl_Yolo.so: cannot open shared object file
  ```
* **Nguyên nhân:** File cấu hình `config_infer_primary.txt` tham chiếu đến file thư viện parse box custom của YOLOv5/YOLO11 nhưng thư viện này chưa được biên dịch trên môi trường hiện tại.
* **Khắc phục:** Thực hiện `make -C /app/DeepStream-Yolo` để sinh ra file `.so` và kiểm tra quyền thực thi `chmod 755`.

#### 10. Sự cố `ERR-PIPE-03`: Lỗi Giải Mã TensorRT Engine Do Không Tương Thích Kiến Trúc
* **Hiện tượng:**
  ```text
  ERROR: Deserialize engine failed because file path: /workspace/configs/exp.engine open error
  ```
* **Nguyên nhân:** File `.engine` được build trên máy tính cá nhân (x86_64, CUDA 12, RTX GPU) rồi copy sang Jetson Nano (aarch64, CUDA 10.2, Maxwell GPU). TensorRT Engine có tính chất gắn chặt cứng với phần cứng, không thể chạy chéo kiến trúc.
* **Khắc phục:** Chỉ chia sẻ file mô hình gốc `.onnx` sang Jetson Nano, để DeepStream tự động build `.engine` trực tiếp trên Jetson trong lần chạy đầu tiên.

#### 11. Sự cố `ERR-PIPE-04`: Lỗi Gõ Nhầm Tham Số Dòng Lệnh
* **Hiện tượng:**
  ```text
  app_custom.py: error: unrecognized arguments: --sourve csi
  main_roi_traffic_fixed.py: error: argument --source-fps: invalid float value: '/dev/video0'
  ```
* **Nguyên nhân:** Gõ sai chính tả `--sourve` thay vì `--source`, hoặc đảo lộn vị trí giữa tham số cờ và giá trị truyền vào.
* **Khắc phục:** Cập nhật script `restart_edge.sh` và `main.py` dùng `argparse` với giá trị mặc định rõ ràng, kiểm tra validate kiểu dữ liệu chặt chẽ.

#### 12. Sự cố `ERR-PIPE-05`: Video Chạy Hết Frame Tự Động Thoát (End of Stream - EOS)
* **Hiện tượng:** Hệ thống chạy rất mượt 20-30 giây đầu rồi tự ngắt kết nối, WebGIS chuyển sang trạng thái `OFFLINE`. Log báo:
  ```text
  [PIPELINE] End of stream
  [NvMultiObjectTracker] De-initialized
  ```
* **Nguyên nhân:** Khi nguồn phát là file `.mp4`, GStreamer phát tín hiệu EOS khi đến frame cuối và tự dừng luồng.
* **Khắc phục:** 
  - Trong chế độ thực địa: Dùng camera CSI phần cứng `--source csi` (luồng vô tận).
  - Trong chế độ thử nghiệm file: Sử dụng pipeline lặp video hoặc tạo script phát lại tuần hoàn.

#### 13. Sự cố `ERR-PIPE-06`: Lỗi Gọi Phương Thức Không Tồn Tại Trên Đối Tượng PyDS
* **Hiện tượng:**
  ```text
  AttributeError: 'pyds.NvOSD_TextParams' object has no attribute 'set_font_size'
  ```
* **Nguyên nhân:** Trong NVIDIA DeepStream Python Bindings (`pyds`), cỡ chữ được thiết lập trực tiếp qua thuộc tính `font_params.font_size = 12`, không có hàm getter/setter kiểu Java.
* **Khắc phục:**
  ```python
  txt_params.font_params.font_name = "Arial"
  txt_params.font_params.font_size = 11
  txt_params.font_params.font_color.set(1.0, 1.0, 1.0, 1.0)
  ```

#### 14. Sự cố `ERR-PIPE-07`: Lệch Số Lượng Surface Đầu Vào Của NvStreamMux
* **Hiện tượng:**
  ```text
  [!] GStreamer Error: gst-stream-error-quark: Input buffer number of surfaces (0) must be equal to mux
  ```
* **Nguyên nhân:** Định dạng đệm hình ảnh cấp phát từ phần tử giải mã phần mềm không được nạp vào bộ nhớ đồ họa dùng chung (NVMM) trước khi đưa vào `nvstreammux`.
* **Khắc phục:** Thêm phần tử `nvvideoconvert` với caps `'video/x-raw(memory:NVMM)'` trước cổng `sink_0` của `nvstreammux`.

---

### 🧠 NHÓM 3: THUẬT TOÁN AI, TRACKER, MA TRẬN HOMOGRAPHY & LOGIC ĐẾM XE

#### 15. Sự cố `ERR-AI-01`: Thiếu Lớp Phương Tiện Tiếng Việt Trong Bộ Nhãn
* **Hiện tượng:**
  ```text
  main_roi_traffic.py: error: Vehicle classes missing from labels: o_to, xe_buyt, xe_may, xe_tai
  ```
* **Nguyên nhân:** Code phân tích giao thông kiểm tra danh sách nhãn bắt buộc phải có tên tiếng Việt không dấu, nhưng model đang load lại trả về nhãn tiếng Anh của tập dữ liệu COCO (`car`, `bus`, `motorcycle`, `truck`).
* **Khắc phục:** Xây dựng từ điển ánh xạ nhãn linh hoạt hai chiều (`LABEL_MAPPING`):
  ```python
  CLASS_MAP = {
      "car": "o_to", "automobile": "o_to", "o_to": "o_to",
      "bus": "xe_buyt", "xe_buyt": "xe_buyt",
      "motorcycle": "xe_may", "motorbike": "xe_may", "xe_may": "xe_may",
      "truck": "xe_tai", "xe_tai": "xe_tai"
  }
  ```

#### 16. Sự cố `ERR-AI-02`: Vận Tốc Phương Tiện Ra Số Âm Hoặc Nhảy Vọt Bất Thường
* **Hiện tượng:** Đo vận tốc xe trên WebGIS hiển thị `0.08 km/h` hoặc vọt lên `240 km/h`, thậm chí có giá trị âm.
* **Nguyên nhân:**
  1. **Thứ tự 4 điểm hiệu chuẩn Homography:** Ma trận biến đổi phối cảnh 2D sang mặt bằng thực tế (BEV) yêu cầu thứ tự 4 điểm nghiêm ngặt: `[Top-Left, Top-Right, Bottom-Right, Bottom-Left]`. Người dùng chọn điểm theo thứ tự ziczac dẫn đến ma trận nghịch đảo bị xoắn.
  2. **Tọa độ neo Bounding Box:** Lấy tâm hình chữ nhật `(cx, cy)` để tính vận tốc thay vì lấy tâm đáy `(cx, bottom_y)`. Do góc chúc của camera, phần nóc xe bị biến dạng phối cảnh mạnh hơn mặt đường tiếp xúc bánh xe.
* **Khắc phục:**
  - Viết script `tools/validate_calibration.py` để kiểm tra độ co giãn hình học của 4 điểm trước khi lưu.
  - Sử dụng điểm neo tiếp xúc mặt đường: `anchor_point = (bbox[0] + bbox[2] / 2, bbox[3])`.

#### 17. Sự cố `ERR-AI-03`: Nhảy Số Track ID và Đếm Lặp Khi Xe Bị Che Khuất
* **Hiện tượng:** Một chiếc xe di chuyển qua ROI bị đếm thành 2-3 lượt phương tiện.
* **Nguyên nhân:** Thuật toán ByteTrack mất dấu khi xe bị che khuất (occlusion) bởi xe buýt/xe tải, sau đó tạo một `track_id` mới và tiếp tục kích hoạt sự kiện đi vào ROI lần hai.
* **Khắc phục:**
  - Bổ sung ngưỡng thời gian trễ xác nhận vào ROI (`enter_confirm_seconds = 0.5s`).
  - Lưu vết lịch sử trọng tâm quỹ đạo và đối chiếu khoảng cách không gian (Spatial IoU Matching) trước khi cấp phát ID mới.

#### 18. Sự cố `ERR-AI-04`: Cảnh Báo Kẹt Xe Ảo Tại Giao Lộ Có Đèn Tín Hiệu
* **Hiện tượng:** Đường rất thông thoáng nhưng khi dừng đèn đỏ 20 giây, hệ thống lập tức báo trạng thái `CONGESTED` mức độ đỏ và kích hoạt chụp ảnh sự cố liên tục.
* **Nguyên nhân:** Thuật toán đánh giá ban đầu chỉ căn cứ vào vận tốc trung bình tức thời `< 10 km/h` mà không xét đến chu kỳ đèn tín hiệu và mật độ phương tiện chiếm dụng thực tế.
* **Khắc phục:** 
  - Nâng cấp mô hình phân loại giao thông `TrafficStateModel`: Kết hợp 3 trọng số: Vận tốc trung bình (50%), Mật độ phương tiện (30%), và Tỷ lệ xe dừng đỗ (20%).
  - Bổ sung bộ lọc thời gian xác nhận ùn tắc `CONGESTION_CONFIRM_SECONDS = 15.0s` và thời gian hồi chiêu snapshot `COOLDOWN_SECONDS = 60.0s`.

#### 19. Sự cố `ERR-AI-05`: Lỗi Unicode Khi Lưu File Cấu Hình ROI
* **Hiện tượng:**
  ```text
  ERROR: Khong the luu /workspace/configs/roi.json: 'ascii' codec can't encode characters in position ...
  ```
* **Nguyên nhân:** Tên nút giao thông hoặc tên làn đường có dấu tiếng Việt (ví dụ: `Ngã tư Hàng Xanh`), hàm `open('roi.json', 'w')` trên hệ điều hành Linux mặc định dùng mã hóa ASCII khi biến môi trường `LANG` chưa thiết lập UTF-8.
* **Khắc phục:**
  ```python
  with open(filepath, 'w', encoding='utf-8') as f:
      json.dump(data, f, ensure_ascii=False, indent=2)
  ```

#### 20. Sự cố `ERR-AI-06` (D2): Dự Báo Ùn Tắc 5/10 Phút Hồi Quy Tuyến Tính Cục Bộ Tại Edge Gây Lãng Phí Tài Nguyên
* **Hiện tượng:** Jetson Edge liên tục tính ma trận hồi quy tuyến tính xu hướng 5/10 phút từ hàng đợi 300 giây và gửi kèm trường `forecast` vào telemetry mỗi giây một lần, nhưng Backend và Frontend không lưu trữ hay hiển thị.
* **Nguyên nhân:**
  1. Hồi quy tuyến tính 1 chiều tại một camera cục bộ không thể phản ánh tính phi tuyến của dòng xe và bị "mù" trước dữ liệu mạng lưới đa trạm.
  2. Việc tính toán và gửi mỗi giây gây lãng phí chu kỳ CPU trên Jetson và phình to băng thông mạng MQTT vô ích.
* **Khắc phục:**
  1. Thêm cờ cấu hình `ENABLE_EDGE_FORECAST = False` (mặc định tắt) trong `config/settings.py` và `communication/mqtt_client.py` để tinh gọn payload telemetry và giải phóng CPU Edge.
  2. Chuyển giao toàn bộ tính năng này thành **Module AI Dự Báo Ùn Tắc Tập Trung Tại Server (Centralized AI Forecasting)** dựa trên dữ liệu chuỗi thời gian SQLite `traffic_timeline` (từ sự cố D1). Chi tiết lộ trình huấn luyện mô hình XGBoost/LSTM đã được tài liệu hóa đầy đủ tại [HUONG_PHAT_TRIEN_AI_DU_BAO_KET_XE.md](file:///d:/edge-ai-web/HUONG_PHAT_TRIEN_AI_DU_BAO_KET_XE.md).

#### 21. Sự cố `ERR-AI-07` (A1): Lệch Pha Giữa Mật Độ Hiển Thị Và Mật Độ Phân Loại (Raw Vehicles vs. PCE Density)
* **Hiện tượng:** Trên WebGIS, mật độ hiển thị số xe rất cao (ví dụ 160 xe/km/làn khi có nhiều xe máy), nhưng trạng thái phân loại vẫn báo `FREE` dù tài liệu ghi ngưỡng phân loại là 140/220 xe/km/làn.
* **Nguyên nhân:** Mô hình phân loại sử dụng Mật độ quy đổi tương đương xe con (`pce_density` với hệ số xe máy = 0.30 PCU theo TCVN 4054), nhưng trước đây `density_veh_per_km_lane` trả về số lượng xe vật lý thô (`density_raw`).
* **Khắc phục:** Tách bạch và chuẩn hóa định danh 2 trường dữ liệu trong telemetry: `density_raw_veh_per_km_lane` (mật độ đếm số xe) và `density_pce_per_km_lane` (mật độ quy đổi PCU). Hiển thị song song trên OSD camera: `Density raw: %.1f v/km` và `PCE: %.1f pcu/km`.

#### 22. Sự cố `ERR-AI-08` (A2): Ngưỡng Điểm Ùn Tắc & Bảng Màu Bị Rải Rác Ở Nhiều Nơi
* **Hiện tượng:** Ngưỡng màu (Xanh ≤35, Vàng 35–65, Đỏ ≥65) bị code lặp lại ở 3 module khác nhau (`traffic_classifier.py`, `main.py`, WebGIS components). Nếu cần tinh chỉnh độ nhạy phải sửa ở nhiều nơi, dễ gây xung đột hiển thị.
* **Nguyên nhân:** Thiếu định nghĩa cấu hình tập trung (Single Source of Truth) cho bảng màu và ngưỡng trạng thái.
* **Khắc phục:** Khai báo hằng số tập trung `CONGESTION_THRESHOLDS` và bảng màu `TRAFFIC_COLORS` chuẩn tại `analytics/traffic_classifier.py`; cung cấp hàm trợ năng `get_traffic_color(score, status)` dùng chung toàn hệ thống.

#### 23. Sự cố `ERR-AI-09` (A3): Điểm Mù Khi Ít Xe Dừng Bất Động (Bảo Vệ Đơn Thuần `< 3 Xe Luôn Là FREE`)
* **Hiện tượng:** Khi chỉ có 1–2 xe chết máy hoặc gặp tai nạn nằm bất động 100% trong đoạn ROI ngắn, hệ thống vẫn duy trì nhãn `FREE` (0 điểm) do cơ chế bảo vệ số lượng xe thấp (`vehicle_count <= 2`).
* **Nguyên nhân:** Thuật toán chỉ bảo vệ chống bùng nổ mật độ ảo mà không theo dõi thời gian dừng bất động liên tục của các phương tiện này.
* **Khắc phục:** Tích hợp bộ đếm thời gian dừng bất động liên tục (`stationary_incident_threshold_s = 30.0s`). Khi $\le 2$ xe nhưng có phương tiện đứng yên liên tục quá 30 giây: kích hoạt cờ `_incident_detected = True`, chuyển trạng thái sang `SLOW` và nâng điểm ùn tắc lên 45 điểm để kích hoạt cảnh báo sự cố giao thông.

#### 24. Sự cố `ERR-AI-10` (A4): Mặc Định `--algo-version` Chạy V1 Gây Báo Kẹt Giả Tại Đèn Đỏ
* **Hiện tượng:** Khi chạy trực tiếp `python main.py` mà không truyền tham số, hoặc trong môi trường `.env.example`, hệ thống dùng thuật toán V1 (Spatial Snapshot) khiến camera liên tục báo kẹt xe giả mỗi chu kỳ đèn đỏ 20–30 giây.
* **Nguyên nhân:** Giá trị tham số mặc định trong `argparse` và `.env.example` là `v1`.
* **Khắc phục:** Nâng cấp mặc định toàn hệ thống sang `v2` (Context-Aware Dwell-Time) trong cả `main.py` và `.env.example`.

#### 25. Sự cố `ERR-AI-11` (A5): Rò Rỉ Bộ Nhớ (Memory Leak) Khi Vận Hành Camera 24/7 Tại `track_prev_area`
* **Hiện tượng:** Sau nhiều ngày chạy liên tục, tiến trình `main.py` tiêu tốn thêm RAM và suy giảm hiệu năng do kích thước dictionary `track_prev_area` tăng tuyến tính theo số lượng xe đã đi qua.
* **Nguyên nhân:** `track_prev_area` chỉ thêm diện tích của các track mới mà không có hàm dọn dẹp (pruning) các track đã rời khỏi camera.
* **Khắc phục:** Chuyển sang lưu cặp tuple `(current_area, last_seen_time)` và bổ sung cơ chế quét định kỳ mỗi 5 giây: tự động xóa toàn bộ các track không xuất hiện trong vòng 10 giây (`stale_area_keys`).

#### 26. Sự cố `ERR-AI-12` (A6): Benchmark So Sánh V1/V2 Chưa Thuyết Phục & Thiếu Chỉ Số Khoa Học
* **Hiện tượng:** File `tools/compare_congestion_models.py` trước đây chỉ tính tỷ lệ dự đoán đúng cơ bản trên 4 kịch bản tự sinh, thiếu các chỉ số đo lường học máy tiêu chuẩn (Precision, Recall, F1, FAR/hour) và không hỗ trợ nạp log dữ liệu thật.
* **Khắc phục:**
  - Bổ sung ma trận nhầm lẫn (Confusion Matrix: TP, FP, FN, TN) cho sự kiện ùn tắc `CONGESTED`.
  - Tính toán và in bảng đối chứng chuẩn quốc tế: Độ chính xác phát hiện (Precision), Độ nhạy/Thu hồi (Recall), F1-Score, và Tần suất báo động giả trên mỗi giờ hoạt động (`FAR/Hour`).
  - Hỗ trợ tham số `--input-log <file>` để nạp dữ liệu log thực tế (CSV/JSONL) khi đánh giá thực nghiệm cho khóa luận.

---

### 🌐 NHÓM 4: GIAO TIẾP MẠNG IOT, MQTT HIVEMQ CLOUD & ĐỒNG BỘ TRẠNG THÁI

#### 20. Sự cố `ERR-NET-01`: Lỗi Văng Kết Nối MQTT `rc=7` (`MQTT_ERR_CONN_LOST`)
* **Hiện tượng:** Log Jetson và Backend in lặp liên tục mỗi vài giây:
  ```text
  [MQTT] Disconnected for edge-01 (rc=7), reconnecting...
  ```
* **Nguyên nhân cốt lõi (Root Cause):** Hai hoặc nhiều tiến trình kết nối vào HiveMQ Cloud Broker dùng **CHUNG một Client ID** (`edge-01`). Chuẩn giao thức MQTT quy định khi có Client mới kết nối với cùng ID, Broker bắt buộc phải ngắt kết nối (kick out) Client cũ. Vì các client đều có cơ chế auto-reconnect, chúng liên tục đá văng nhau vòng tròn vô tận.
* **Khắc phục:** Thiết lập Client ID cố định và phân tách tuyệt đối:
  - Jetson Agent: `edge-01-agent`
  - Pipeline Worker: `edge-01-pipeline`
  - Snapshot Tool: `edge-01-snapshot`
  - WebGIS Backend: `webgis-backend-hub`
  - Maintenance Tool: `edge-01-maint`

#### 21. Sự cố `ERR-NET-02`: Lỗi Không Thể Định Tuyến Đến Broker (`No route to host`)
* **Hiện tượng:**
  ```text
  [MQTT] Connection failed: [Errno 113] No route to host
  ```
* **Nguyên nhân:** Cấu hình DNS trên Jetson Nano bị lỗi (`/etc/resolv.conf`), hoặc Jetson đang kết nối vào mạng WiFi công cộng chặn cổng bảo mật TLS `8883`.
* **Khắc phục:**
  - Bổ sung DNS Google vào `/etc/resolv.conf`: `nameserver 8.8.8.8`.
  - Kiểm tra kết nối TLS: `openssl s_client -connect <broker-url>:8883`.

#### 22. Sự cố `ERR-NET-03`: Biến `parts` Chưa Khai Báo Nuốt Chửng Bản Tin Telemetry
* **Hiện tượng:** Jetson gửi bản tin đều đặn nhưng WebGIS hiển thị xám xịt và báo `OFFLINE`.
* **Nguyên nhân:** Trong `webgis/backend/services/mqtt_service.py`:
  ```python
  if topic == "traffic/discovery/announce" or (len(parts) >= 3 and parts[2] == "announce"):
  ```
  Biến `parts` chưa được định nghĩa trước dòng này, làm ném ngoại lệ `NameError: name 'parts' is not defined`. Khối `except` chung bắt ngoại lệ và bỏ qua gói tin mà không log rõ ràng.
* **Khắc phục:** Khai báo ngay ở đầu hàm:
  ```python
  topic = msg.topic
  parts = topic.split('/')
  payload = json.loads(msg.payload.decode("utf-8"))
  ```

#### 23. Sự cố `ERR-NET-04`: Báo Offline Giả Khi Tắt Pipeline Con
* **Hiện tượng:** Người dùng dừng pipeline AI (`main.py`) thì trên bản đồ WebGIS, camera bị đánh dấu `OFFLINE`, mặc dù thiết bị Jetson và Agent vẫn đang cắm nguồn hoạt động bình thường.
* **Nguyên nhân:** Khi hàm `stop()` của `main.py` được gọi, nó publish bản tin `status: offline` lên MQTT.
* **Khắc phục:** Quy định kiến trúc: **Chỉ có Jetson Agent và cơ chế MQTT LWT (Last Will and Testament) mới có quyền công bố trạng thái nguồn của thiết bị**. Pipeline Worker khi dừng chỉ thông báo trạng thái `pipeline_status: stopped`.

#### 24. Sự cố `ERR-NET-05`: Lỗi Event Loop trong MQTT Callback Thread
* **Hiện tượng:**
  ```text
  [!] Error processing MQTT message: There is no current event loop in thread 'Thread-1'
  ```
* **Nguyên nhân:** Thư viện `paho-mqtt` nhận gói tin trên một luồng nền riêng (C-thread). Khi gọi trực tiếp các hàm bất đồng bộ (`async def`) của FastAPI/WebGIS, Python báo lỗi vì luồng này không sở hữu asyncio event loop.
* **Khắc phục:** Sử dụng hàm điều phối an toàn qua các luồng:
  ```python
  asyncio.run_coroutine_threadsafe(broadcast_to_websocket(data), main_event_loop)
  ```

#### 25. Sự cố `ERR-NET-06`: Lệch Cấu Hình `EDGE_ID` Giữa Backend và Jetson
* **Hiện tượng:** WebGIS bấm nút điều khiển Jetson nhưng Jetson không có bất kỳ phản hồi nào.
* **Nguyên nhân:** Danh sách duyệt nút `approved_nodes.json` trên Backend ghi mã `edge-01`, nhưng file `.env` trên Jetson lại đặt `EDGE_ID=jetson-orin-01`. Do đó, lệnh MQTT gửi xuống topic `traffic/edge-01/command` không có ai lắng nghe.
* **Khắc phục:** Thêm cơ chế **Dynamic Discovery Announce**: Khi Jetson khởi động, Agent gửi bản tin MAC Address và Serial Number lên `traffic/discovery/announce`, Backend tự động đối chiếu và đồng bộ mã Node chính xác.

---

### 📺 NHÓM 5: STREAMING VIDEO TRỰC TIẾP MEDIAMTX (RTSP, WEBRTC, WHEP)

#### 26. Sự cố `ERR-STR-01`: RTSP Client Sink Không Mở Được Tài Nguyên Để Đẩy Luồng
* **Hiện tượng:**
  ```text
  ERROR: from element /GstPipeline:pipeline0/GstRTSPClientSink:rtspclientsink0: Could not open resource for writing.
  ```
* **Nguyên nhân:** Tiến trình MediaMTX chưa được khởi động trên máy chủ, hoặc cổng RTSP `8554` bị chặn, hoặc đường dẫn mount path sai cú pháp.
* **Khắc phục:** 
  - Khởi động MediaMTX: `./mediamtx.exe` (hoặc container `mediamtx`).
  - Kiểm tra listening port bằng PowerShell: `Get-NetTCPConnection -LocalPort 8554`.

#### 27. Sự cố `ERR-STR-02`: Lỗi Tham Số Cấu Hình Profile Bộ Mã Hóa Phần Cứng `nvv4l2h264enc`
* **Hiện tượng:**
  ```text
  WARNING: erroneous pipeline: could not set property "profile" on "nvv4l2h264enc"
  ```
* **Nguyên nhân:** Thuộc tính `profile` trên phần tử mã hóa phần cứng của Jetson Nano nhận giá trị dạng số nguyên Enum `profile=1` (Main) hoặc `profile=0` (Baseline), truyền dạng chuỗi `'Main'` bị parser GStreamer từ chối.
* **Khắc phục:** Đặt chuẩn: `nvv4l2h264enc bitrate=1500000 insert-sps-pps=true idrinterval=15 profile=1`.

#### 28. Sự cố `ERR-STR-03`: Xung Đột Cảm Biến Camera CSI Khi Vừa Stream Vừa Snapshot
* **Hiện tượng:** Khi đang bật tính năng xem camera trực tiếp, nếu người dùng bấm nút "Chụp ảnh kiểm tra" thì luồng live bị đơ và chức năng chụp ảnh báo lỗi `Device or resource busy`.
* **Nguyên nhân:** Cả hai tính năng đều cố gắng mở `/dev/video0` hoặc gọi `nvarguscamerasrc` mới độc lập. Phần cứng Jetson Nano chỉ cho phép 1 tiến trình duy nhất chiếm quyền cảm biến CSI tại một thời điểm.
* **Khắc phục:** Thiết kế lại cơ chế lấy khung hình: Không mở thêm camera source mới. Sử dụng phần tử `tee` trong GStreamer để rẽ nhánh luồng dữ liệu, hoặc lấy trực tiếp mảng đệm NumPy frame từ tiến trình Pipeline đang chạy.

#### 29. Sự cố `ERR-STR-04`: WebRTC / WHEP Bị Tường Lửa Windows Chặn Gói Tin UDP
* **Hiện tượng:** Trên WebGIS, người dùng mở xem trực tiếp thì đầu phát quay vòng tròn vô tận hoặc báo lỗi kết nối WHEP.
* **Nguyên nhân:** WebRTC sử dụng các cổng UDP ngẫu nhiên (mặc định dải `8189/udp`) và cổng TCP `8889` cho tín hiệu bắt tay WHEP. Tường lửa Windows tự động chặn các gói tin UDP chưa được khai báo.
* **Khắc phục:** Tạo script mở cổng tự động [open_firewall_mediamtx.bat](file:///d:/edge-ai-web/open_firewall_mediamtx.bat):
  ```bat
  netsh advfirewall firewall add rule name="MediaMTX_WebRTC_TCP" dir=in action=allow protocol=TCP localport=8889
  netsh advfirewall firewall add rule name="MediaMTX_WebRTC_UDP" dir=in action=allow protocol=UDP localport=8189
  ```

---

### 🖥️ NHÓM 6: WEBGIS BACKEND (FASTAPI, SQLITE, SCHEMA & ENVIRONMENT)

#### 30. Sự cố `ERR-BE-01`: Xung Đột Cổng 8000 Khi Khởi Động Backend (`Errno 10048`)
* **Hiện tượng:**
  ```text
  ERROR: [Errno 10048] error while attempting to bind on address ('0.0.0.0', 8000): only one usage of each socket address is normally permitted
  ```
* **Nguyên nhân:** Tiến trình Python uvicorn cũ chưa được giải phóng hoàn toàn, vẫn đang chạy ngầm chiếm cổng 8000.
* **Khắc phục:** Tìm và tắt tiến trình chiếm cổng:
  ```powershell
  Get-Process -Id (Get-NetTCPConnection -LocalPort 8000).OwningProcess | Stop-Process -Force
  ```

#### 31. Sự cố `ERR-BE-02`: Lỗi Cấm Truy Cập Socket Trên Windows (`WinError 10013`)
* **Hiện tượng:**
  ```text
  ERROR: [WinError 10013] An attempt was made to access a socket in a way forbidden by its access permissions
  ```
* **Nguyên nhân:** Dịch vụ mạng Hyper-V hoặc Internet Connection Sharing (ICS) trên Windows chiếm dụng một dải cổng động ngẫu nhiên bao gồm cổng được cấu hình.
* **Khắc phục:** Đổi cổng backend sang cổng thay thế (ví dụ `8001`) hoặc khởi động lại dịch vụ WinNAT:
  ```cmd
  net stop winnat && net start winnat
  ```

#### 32. Sự cố `ERR-BE-03`: Lỗi Thiếu Cột Trong Bảng SQLite (`no such column: last_heartbeat`)
* **Hiện tượng:**
  ```text
  [!] SQLite check_offline_cameras error: no such column: last_heartbeat
  ```
* **Nguyên nhân:** Mã nguồn backend bổ sung tính năng theo dõi nhịp tim camera, nhưng cơ sở dữ liệu SQLite cũ `traffic.db` chưa được chạy lệnh migrate thêm cột `last_heartbeat`.
* **Khắc phục:** Thêm kiểm tra tự động chạy script migration lúc khởi động backend:
  ```python
  cursor.execute("PRAGMA table_info(cameras)")
  cols = [row[1] for row in cursor.fetchall()]
  if "last_heartbeat" not in cols:
      cursor.execute("ALTER TABLE cameras ADD COLUMN last_heartbeat REAL")
  ```

#### 33. Sự cố `ERR-BE-04`: Xung Đột Tên Gói Thư Mục `config`
* **Hiện tượng:**
  ```text
  ModuleNotFoundError: No module named 'config.settings'; 'config' is not a package
  ```
* **Nguyên nhân:** Có cả thư mục `config/` và thư mục `configs/`, hoặc một file `config.py` nằm ngang hàng trong `PYTHONPATH` làm Python nhận diện nhầm file đơn thay vì thư mục chứa `__init__.py`.
* **Khắc phục:** Thêm file rỗng `__init__.py` vào thư mục `config/` và chuẩn hóa cấu trúc import từ thư mục gốc.

#### 34. Sự cố `ERR-BE-05`: Phân Mảnh Và Lệch Cấu Hình Biến Môi Trường `.env`
* **Hiện tượng:** Sửa cấu hình MQTT ở file `.env` gốc nhưng Backend vẫn lấy thông tin cũ của HiveMQ khác.
* **Nguyên nhân:** Tồn tại đồng thời 3 file: `.env` ở thư mục gốc, `webgis/backend/.env`, và `webgis/frontend/.env` dẫn đến ghi đè biến không đồng nhất.
* **Khắc phục:** Đồng nhất cơ chế nạp biến môi trường: Đọc ưu tiên từ file `.env` duy nhất tại thư mục gốc dự án.

#### 35. Sự cố `ERR-BE-06` (D4, D8): Ghi Đĩa Liên Tục & Tồn Tại File `.backup.json` Thủ Công
* **Hiện tượng:** Mỗi heartbeat (5s một lần/node) và mỗi 3s đều ghi đè file JSON xuống đĩa; thư mục `data/` tồn tại các file `approved_nodes.backup.json` do từng bị hỏng file.
* **Nguyên nhân:** Thiếu cơ chế Dirty Check (dù dữ liệu không đổi vẫn ghi đĩa) và thiếu Atomic Write chuẩn khi có tắt nóng server.
* **Khắc phục:** 
  - Chỉ ghi `approved_nodes.json` khi có thay đổi cấu hình thực sự (upsert/delete/approve node).
  - Tăng debounce cache trạng thái động từ 3s lên 30s.
  - Chuẩn hóa Atomic Write: Ghi ra file `.tmp` $\to$ `flush()` + `os.fsync()` $\to$ `replace()`.
  - Xóa bỏ hoàn toàn các file `.backup.json` thủ công thừa.

#### 36. Sự cố `ERR-BE-07` (D7): Xung Đột Đa Luồng (Thread-Safety) Giữa Paho-MQTT Thread Và FastAPI Asyncio Loop
* **Hiện tượng:** Xuất hiện lỗi `RuntimeError: dictionary changed size during iteration` khi có nhiều node bắn MQTT và giao diện WebGIS tải đồng thời.
* **Nguyên nhân:** Callback `_on_message` của `paho-mqtt` chạy trên OS background thread, cùng lúc đó FastAPI coroutines duyệt dict trên Main Asyncio Loop mà không có khóa bảo vệ.
* **Khắc phục:** Bảo vệ toàn diện `self.nodes`, `self.segments`, `self.pending_nodes` bằng `threading.RLock()`; các hàm getter luôn trả về bản sao (shallow copy/list) để việc duyệt ngoài lock an toàn 100%.

#### 37. Sự cố `ERR-BE-08` (D5): Node Bật Tắt Online/Offline Chập Chờn Do Lệch Đồng Hồ Thiết Bị
* **Hiện tượng:** Node chập chờn online rồi offline liên tục mỗi 25 giây dù camera vẫn đang gửi tin đều đặn.
* **Nguyên nhân:** Jetson Nano không có pin RTC; sau khi khởi động đồng hồ bị lệch giờ so với Server. Backend dùng `node["last_seen"] = payload["timestamp"]` khiến watchdog tưởng trạm đã mất kết nối.
* **Khắc phục:** Luôn lấy thời gian tiếp nhận tại Server (`datetime.now().isoformat()`) để tính liveness của trạm; hạ MQTT keepalive xuống 15s để LWT phát hiện sự cố nhanh chóng.

#### 38. Sự cố `ERR-BE-09` (D4, D6): WebSocket Broadcast Tuần Tự Gây Nghẽn & Chặn Sự Kiện Quản Trị
* **Hiện tượng:** Một client mạng chậm làm đơ toàn bộ các kết nối WebSocket khác; Admin không nhận được thông báo `device_pending` tự động mà phải bấm F5 / poll REST.
* **Nguyên nhân:** `broadcast()` dùng `await connection.send_text()` tuần tự trong vòng lặp; Frontend kết nối WS ẩn danh không kèm JWT token nên Server lọc quyền chặn sự kiện nhạy cảm.
* **Khắc phục:** 
  - Chuyển `broadcast()` sang `asyncio.gather` song song kèm timeout 1.5s riêng cho từng client để cô lập client chậm.
  - Gửi JWT token qua query param `/ws?token=...` và thông điệp `authenticate` khi đăng nhập.
  - Heartbeat chỉ gửi delta trạng thái thay vì dump toàn bộ cấu trúc node; tự động kích hoạt `onReconnect` đồng bộ lại dữ liệu khi socket nối lại.

---

### 💻 NHÓM 7: WEBGIS FRONTEND (REACT, VITE, MAPLIBRE GL & GIAO DIỆN ĐIỀU HÀNH)

#### 35. Sự cố `ERR-FE-01`: Vi Phạm Thứ Tự Gọi React Hooks (`Rules of Hooks`)
* **Hiện tượng:**
  ```text
  NodeDashboardDrawer.tsx:28 React has detected a change in the order of Hooks called by NodeDashboardDrawer
  ```
* **Nguyên nhân:** Khai báo các hook `useMemo`, `useEffect` nằm bên dưới lệnh điều kiện thoát sớm:
  ```tsx
  if (!node) return null; // <- Thoát sớm ở đây
  const stats = useMemo(() => calculateStats(node), [node]); // <- Hook bị gọi không đều giữa các lần render
  ```
* **Khắc phục:** Đưa toàn bộ các lệnh Hooks lên đầu component trước bất kỳ câu lệnh `if...return` nào.

#### 36. Sự cố `ERR-FE-02`: Lỗi Đọc Thuộc Tính Của Đối Tượng Rỗng (`undefined / null`)
* **Hiện tượng:** Giao diện Dashboard sập màn hình trắng khi nhận gói tin telemetry đầu tiên:
  ```text
  Uncaught TypeError: Cannot read properties of undefined (reading 'toLowerCase')
  ```
* **Nguyên nhân:** Bản tin telemetry từ camera mới kết nối chưa có trường `traffic_status` hoặc danh sách `vehicle_counts` bị rỗng.
* **Khắc phục:** Sử dụng toán tử kiểm tra an toàn (Optional Chaining) và giá trị dự phòng (Nullish Coalescing):
  ```tsx
  const status = node?.telemetry?.traffic_status?.toLowerCase() ?? 'unknown';
  ```

#### 37. Sự cố `ERR-FE-03`: Lỗi Bất Đồng Bộ Khi Vẽ Heatmap Giao Thông Lên MapLibre GL
* **Hiện tượng:** Bản đồ không hiển thị lớp heatmap mật độ xe, console báo lỗi nguồn layer không tồn tại.
* **Nguyên nhân:** Mã nguồn gọi `map.addSource('traffic-heat', ...)` và `map.addLayer(...)` ngay khi component render, trong khi bản đồ MapLibre chưa tải xong tài nguyên kiểu dáng bản đồ (`map.isStyleLoaded() == false`).
* **Khắc phục:** Đăng ký hàm vẽ bên trong sự kiện sẵn sàng của bản đồ:
  ```tsx
  if (!map.isStyleLoaded()) {
      map.once('styledata', () => renderHeatmapLayers(map));
  } else {
      renderHeatmapLayers(map);
  }
  ```

#### 38. Sự cố `ERR-FE-04`: Đảo Lộn Thứ Tự Tọa Độ Kinh Độ / Vĩ Độ (GeoJSON Coordinate Inversion)
* **Hiện tượng:** Các điểm nút giao thông và vùng ROI bay sang tận Nam Cực hoặc góc đại dương trên bản đồ.
* **Nguyên nhân:** Nhầm lẫn quy ước tọa độ: Leaflet sử dụng định dạng `[Vĩ độ (Lat), Kinh độ (Lng)]`, trong khi chuẩn GeoJSON và MapLibre GL bắt buộc phải là `[Kinh độ (Lng), Vĩ độ (Lat)]`.
* **Khắc phục:** Chuẩn hóa toàn bộ tọa độ trên WebGIS theo chuẩn GeoJSON: `[longitude, latitude]`.

#### 39. Sự cố `ERR-FE-05`: Vòng Lặp Kết Nối Lại WebSocket Bị Treo Trình Duyệt
* **Hiện tượng:** Console trình duyệt spam hàng nghìn log lỗi:
  ```text
  WebSocket connection to 'ws://localhost:3000/ws' failed: WebSocket is closed before the connection is established.
  ```
* **Nguyên nhân:** Cổng gọi bị sai (`3000` thay vì backend `8000`) và hàm `reconnect()` được gọi trong `useEffect` mà không có thời gian trễ hồi chiêu (Exponential Backoff).
* **Khắc phục:** Cập nhật URL đúng biến môi trường `VITE_WS_URL` và áp dụng thời gian chờ lũy tiến `Math.min(1000 * 2 ** retryCount, 30000)`.

#### 40. Sự cố `ERR-FE-06` (F1): Biểu Thức Khớp Gán Cứng Khiến Node 'edge-01' Đổi Màu Tất Cả Các Tuyến Đường
* **Hiện tượng:** Mỗi khi trạm `edge-01` phát bản tin telemetry, toàn bộ các tuyến đường trong hệ thống WebGIS đều bị tô màu theo trạng thái kẹt xe của trạm này, dù camera đang gắn ở tuyến đường khác.
* **Nguyên nhân:** Biểu thức kiểm tra `matches` trong `setSegmentsGeoJSON` chứa điều kiện OR gán cứng: `msg.edge_id === 'edge-01'` cùng các chuỗi cố định `segId === "seg-edge-01"` và `segment-001`.
* **Khắc phục:** Loại bỏ hoàn toàn các chuỗi ID gán cứng; xây dựng ánh xạ `edgeSegmentMapRef: edge_id -> segment_id`. Chỉ khi `f.properties.segment_id === targetSegmentId` thì tuyến đường mới được cập nhật màu và số liệu.

#### 41. Sự cố `ERR-FE-07` (F2): Bỏ Sót Sự Kiện Cảnh Báo Hạ Tầng (Mã Thiết Bị Lệch, Trôi Dạt GPS & Cập Nhật Đoạn Đường)
* **Hiện tượng:** Backend phát các sự kiện qua WebSocket (`node_mismatch_warning`, `spatial_drift_warning`, `segment_update`), nhưng màn hình WebGIS không phản ứng; cảnh báo sai lệch ID hoặc trôi dạt phần cứng GPS chỉ hiện khi người dùng F5 tải lại trang.
* **Nguyên nhân:** Hàm `wsService.subscribe` trong `WebGISDashboard.tsx` thiếu các nhánh xử lý cho các loại sự kiện trên.
* **Khắc phục:** Bổ sung đầy đủ các bộ lắng nghe sự kiện WebSocket:
  - `segment_update` / `segment_updated`: Tự động cập nhật thuộc tính hoặc bổ sung tuyến đường LineString mới vào `segmentsGeoJSON`.
  - `node_mismatch_warning`: Cập nhật trực tiếp `id_mismatch` và `mismatch_message` vào node state và drawer.
  - `spatial_drift_warning`: Hiển thị khoảng cách trôi dạt GPS phần cứng tức thời vào node state và badge cảnh báo.

#### 42. Sự cố `ERR-FE-08` (F3): Broadcast Khung Hình Preview ROI Base64 Gây Lãng Phí Băng Thông & Lộ Thông Tin
* **Hiện tượng:** Khi một Staff ấn "Lấy hình từ Camera" để vẽ ROI, Backend nén ảnh thành chuỗi Base64 dài hàng trăm KB và phát sóng qua WebSocket cho toàn bộ tất cả người dùng và nhân viên đang kết nối.
* **Nguyên nhân:** Thiếu cơ chế định tuyến gửi thông điệp riêng biệt (targeted message) và sử dụng định dạng Base64 (làm phình to kích thước thêm ~33%).
* **Khắc phục:**
  - Backend ghi nhận `userId` của Staff thực hiện yêu cầu (`_preview_requesters[request_id] = user_id`).
  - Khi camera gửi ảnh về, WebSocket chỉ truyền URL HTTP GET gọn nhẹ (`preview_url: /api/v1/nodes/{edge_id}/preview/{request_id}/image`), giảm kích thước gói tin từ ~250KB xuống dưới ~200 bytes.
  - Sử dụng `ws_manager.send_to_user` để gửi riêng biệt cho socket của người yêu cầu; cung cấp endpoint HTTP GET trả về nhị phân trực tiếp với `media_type="image/jpeg"`.

---

### 📡 NHÓM 8: ĐIỀU KHIỂN TỪ XA, CHỤP ẢNH SNAPSHOT & BỘ NHỚ ĐỆM NGOẠI TUYẾN (OUTBOX)

#### 40. Sự cố `ERR-CMD-01`: Lỗi Tham Chiếu Biến `frame` Chưa Khởi Tạo Trong Xử Lý Lệnh
* **Hiện tượng:**
  ```text
  [CMD] Handler error for capture_preview: capture preview failed: local variable 'frame' referenced before assignment
  ```
* **Nguyên nhân:** Biến `frame = pipeline.get_current_frame()` nằm trong khối lệnh `try`, khi pipeline chưa có frame hoặc đang khởi động, code nhảy xuống khối `finally` hoặc xử lý tiếp nhưng biến `frame` chưa từng được gán giá trị.
* **Khắc phục:** Khởi tạo giá trị mặc định ở đầu hàm: `frame = None`.

#### 41. Sự cố `ERR-CMD-02`: Thiếu Thư Viện NumPy Trong Script Chụp Ảnh Snapshot
* **Hiện tượng:**
  ```text
  [CMD] Handler error for capture_preview: capture preview failed: name 'np' is not defined
  ```
* **Nguyên nhân:** Mã nguồn gọi hàm chuyển đổi mảng ảnh `np.asarray(...)` nhưng ở phần header file quên lệnh `import numpy as np`.
* **Khắc phục:** Bổ sung `import numpy as np` đầy đủ ở đầu file.

#### 42. Sự cố `ERR-CMD-03`: Tiến Trình Zombie Vẫn Giữ Khóa Camera Khi Bấm Dừng
* **Hiện tượng:** Người dùng nhấn nút "Dừng Camera" trên WebGIS Dashboard, Backend gửi lệnh `stop_pipeline` thành công, nhưng đèn camera trên Jetson vẫn sáng và không thể khởi động lại luồng mới.
* **Nguyên nhân:** Tiến trình `main.py` được khởi chạy bằng `subprocess.Popen`. Lệnh dừng chỉ gửi tín hiệu `SIGTERM` đến tiến trình cha, các tiến trình con (GStreamer pipeline thread) bị biến thành zombie và tiếp tục chiếm giữ cảm biến.
* **Khắc phục:** Khởi tạo tiến trình bằng nhóm tiến trình (process group) và dừng toàn bộ nhánh:
  ```python
  # Khi khởi chạy:
  proc = subprocess.Popen(cmd, preexec_fn=os.setsid)
  # Khi dừng an toàn:
  os.killpg(os.getpgid(proc.pid), signal.SIGINT)
  ```

#### 43. Sự cố `ERR-CMD-04`: Treo Tiến Trình Ngoại Tuyến Khi Tải Lại Ảnh (Offline Outbox Retry Loop)
* **Hiện tượng:** Khi Jetson mất mạng với Backend, ảnh chụp kẹt xe được lưu vào thư mục `outbox/`. Khi có mạng trở lại, log in liên tục:
  ```text
  Upload pending (ValueError); JPEG retained
  ```
* **Nguyên nhân:** Payload ảnh gửi qua HTTP POST bị lỗi serialize chuỗi base64 hoặc headers chứa ký tự đặc biệt, khiến Backend trả về mã lỗi `422 Unprocessable Entity`. Client hiểu nhầm là lỗi mạng nên giữ nguyên file và thử lại vô tận làm nghẽn hàng đợi.
* **Khắc phục:** Phân loại mã phản hồi HTTP: Nếu là lỗi kết nối mạng (Network Error / Timeout), giữ lại ảnh trong outbox; nếu là mã `4xx` (Bad Request / Data invalid), di chuyển ảnh sang thư mục `outbox_failed/` để tránh nghẽn luồng.

---

### 🛡️ NHÓM 9: AN TOÀN THÔNG TIN, BẢO MẬT & HARDENING (S1 — S8)

#### 44. Sự cố `ERR-SEC-01` (S4): Lỗ Hổng Ghi Tệp Tùy Ý (Path Traversal) Qua `edge_id` & Thiếu Kiểm Tra Magic Bytes
* **Hiện tượng:** Kẻ tấn công có thể gửi tham số `edge_id=../../malicious` trong multipart upload để ghi file ra ngoài thư mục lưu trữ `snapshots/`; tải lên file độc hại giả mạo đuôi `.jpg`.
* **Nguyên nhân:** Backend nối trực tiếp chuỗi `filename = f"{edge_id}_{uuid}.jpg"` mà không kiểm tra tính hợp lệ; không giới hạn kích thước upload và không đọc byte nhận dạng tệp.
* **Khắc phục:** 
  - Kiểm tra regex nghiêm ngặt: `^[a-zA-Z0-9_-]+$`, từ chối ngay lập tức nếu chứa `../` hoặc ký tự đặc biệt.
  - Kiểm tra đường dẫn tuyệt đối: `dest_path.is_relative_to(SNAPSHOTS_STORAGE_DIR)`.
  - Giới hạn kích thước file tối đa 10MB (HTTP 413).
  - Kiểm tra Magic Bytes nhị phân: chỉ chấp nhận JPEG (`\xff\xd8\xff`) và PNG (`\x89PNG`).

#### 45. Sự cố `ERR-SEC-02` (S2): Khóa Xác Thực `EDGE_TOKEN` Bị Vô Hiệu Hóa Bởi Whitelist Cố Định & Log Rò Rỉ
* **Hiện tượng:** Backend chấp nhận các token tĩnh dev (`dev-edge-token`, `my_secret_traffic_token_2026`) khiến token cấu hình không phát huy tác dụng bảo vệ; log in toàn bộ token thô ra console mỗi lần upload.
* **Nguyên nhân:** Khai báo danh sách `valid_tokens` chứa sẵn các chuỗi test và in trực tiếp ra log stdout.
* **Khắc phục:** Xóa bỏ hoàn toàn whitelist tĩnh; chỉ chấp nhận token lấy từ biến môi trường `EDGE_TOKEN`; so sánh hằng thời gian bằng `hmac.compare_digest` chống Timing Attacks; xóa toàn bộ các lệnh in token ra log.

#### 46. Sự cố `ERR-SEC-03` (S3): Endpoint Điều Khiển Luồng Video & Chụp Ảnh Snapshot Không Có Xác Thực
* **Hiện tượng:** Bất kỳ ai trên Internet đều có thể gửi HTTP POST kích hoạt hoặc dừng camera CSI Jetson qua `/live/start|stop`, tải ảnh snapshot và xem danh sách snapshot; lộ địa chỉ MAC của phần cứng cho khách vãng lai.
* **Nguyên nhân:** Các endpoint trong `live.py` và `snapshots.py` thiếu dependency phân quyền; API `GET /nodes` trả về toàn bộ trường dữ liệu thô.
* **Khắc phục:**
  - Bổ sung `require_staff` bảo vệ `/live/start|stop|keepalive` và `GET /snapshots`.
  - Endpoint upload snapshot yêu cầu `X-Edge-Token` hoặc Bearer JWT Staff.
  - Tự động ẩn `mac_address` và `actual_hardware_id` đối với người dùng công khai, chỉ hiển thị khi có token Staff (`get_optional_staff`).

#### 47. Sự cố `ERR-SEC-04` (S5): Máy Chủ MediaMTX Cho Phép Chiếm Đoạt & Đè Luồng RTSP Camera
* **Hiện tượng:** Người dùng ngoài có thể kết nối cổng 8554 và ghi đè luồng RTSP camera của các trạm khác.
* **Nguyên nhân:** Tùy chọn cấu hình `overridePublisher: yes` trong `mediamtx.yml`.
* **Khắc phục:** Thiết lập `overridePublisher: no` trong `deploy/mediamtx/mediamtx.yml`.

#### 48. Sự cố `ERR-SEC-05` (S7): Cấu Hình CORS Mở Bất Hợp Lệ & Giải Mã JWT Lặp Lại
* **Hiện tượng:** `CORSMiddleware` cấu hình `allow_origins=["*"]` kết hợp `allow_credentials=True` vi phạm chuẩn bảo mật W3C và bị trình duyệt hiện đại từ chối; router `commands.py` tự decode JWT thủ công.
* **Nguyên nhân:** Thiết lập origin chung chung dạng wildcard và thiếu đồng nhất dependency xác thực.
* **Khắc phục:** Đặt danh sách origin cụ thể từ biến môi trường `CORS_ORIGINS` (mặc định các cổng của WebGIS frontend); thống nhất dùng `require_staff` trong `commands.py`.

#### 49. Sự cố `ERR-SEC-06` (S1, S8): Rò Rỉ Tệp Phiên Làm Việc & Cơ Chế Fail-Fast Secret Cho Production
* **Hiện tượng:** Gói mã nguồn có nguy cơ chứa tệp phiên thử nghiệm `cookies.txt` và chạy secret mặc định ở môi trường xuất bản.
* **Nguyên nhân:** Thiếu quy tắc trong `.gitignore` và không có điều kiện kiểm tra độ an toàn của khóa khi chuyển sang môi trường `production`.
* **Khắc phục:**
  - Cách ly và chặn hoàn toàn `cookies.txt` qua `.gitignore`.
  - Tích hợp kiểm tra Fail-fast: Nếu `ENVIRONMENT == "production"` mà `JWT_SECRET` hoặc `EDGE_TOKEN` vẫn mang giá trị mặc định kiểu dev, ứng dụng sẽ dừng khởi động ngay lập tức với thông báo lỗi rõ ràng.

---

## 🔒 CHECKLIST VÀNG 10 BƯỚC TRƯỚC KHI CHỈNH SỬA HOẶC TRIỂN KHAI

Để đảm bảo hệ thống vận hành ổn định và không gặp lại bất kỳ lỗi nào trong 43 sự cố trên, hãy tuân thủ checklist 10 bước sau:

1. **Tuyệt đối không trùng MQTT Client ID:** Đảm bảo mỗi file/tiến trình có Client ID riêng biệt (`edge-01-agent`, `edge-01-pipeline`, `webgis-backend-hub`).
2. **Luôn giải phóng Camera CSI bằng `SIGINT` (Ctrl+C):** Không bao giờ dùng `kill -9` ngay lập tức để tránh làm kẹt `nvargus-daemon`.
3. **Kiểm tra trạng thái Camera Daemon:** Nếu camera bị busy, chạy lệnh giải cứu nhanh `sudo systemctl restart nvargus-daemon`.
4. **Kiểm tra nguồn cấp video:** Phân biệt rõ giữa camera live 24/7 (`--source csi`) và video mẫu thử nghiệm (`.mp4` sẽ tự tắt khi hết file).
5. **Đảm bảo thứ tự 4 điểm Homography:** Luôn hiệu chuẩn theo đúng vòng tròn chiều kim đồng hồ: `[Top-Left, Top-Right, Bottom-Right, Bottom-Left]`.
6. **Không đặt React Hooks sau lệnh return:** Mọi hook (`useMemo`, `useEffect`, `useCallback`) phải nằm ở đầu component.
7. **Kiểm tra trạng thái load style của MapLibre:** Chỉ gọi `addSource` và `addLayer` sau khi `map.isStyleLoaded() == true`.
8. **Đồng nhất duy nhất một file cấu hình `.env`:** Tránh phân mảnh cấu hình giữa Jetson, Backend và Frontend.
9. **Mở tường lửa cho MediaMTX:** Đảm bảo mở cả cổng `8554` (RTSP), `8889` (WHEP TCP) và `8189` (WebRTC UDP) trên máy chủ.
10. **Kiểm tra mã hóa file tiếng Việt:** Luôn mở file với tham số `encoding='utf-8'` khi đọc/ghi file cấu hình chứa ký tự tiếng Việt.

---
*Tài liệu được tổng hợp tự động và đối chiếu chi tiết từ 794 yêu cầu và 49 phiên làm việc kỹ thuật.*
