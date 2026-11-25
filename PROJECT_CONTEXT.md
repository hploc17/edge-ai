# 🚦 EDGE AI TRAFFIC MONITORING & WEBGIS - ARCHITECTURE CONTEXT DIGEST
> **Target Audience:** AI Coding Assistants / LLM Agents  
> **Purpose:** Ultra-compressed (<2,500 tokens), zero-fluff architectural summary for immediate context retrieval without parsing heavy files.

---

## 1. Hệ Thống Trong 3 Dòng
Hệ thống giám sát giao thông thông minh biên (Edge AI): **NVIDIA Jetson Nano** chạy mô hình **YOLOv11 + DeepStream (NvDCF tracker)** đếm xe, đo tốc độ calibrated và đánh giá ùn tắc theo ROI. Dữ liệu telemetry và ảnh bằng chứng đẩy qua **HiveMQ Cloud (MQTT TLS)** về **FastAPI Hub**, hiển thị thời gian thực trên **WebGIS Dashboard (React + MapLibre/Leaflet)** kèm luồng phát trực tiếp **MediaMTX (WebRTC/RTSP)**.

---

## 2. Sơ Đồ Luồng Dữ Liệu (3-Tier Architecture)

```
[ Camera CSI / Video File ]
          │ (H.264 / NVMM)
          ▼
┌──────────────────────────────────────── Jetson Nano (Edge) ────────────────────────────────────────┐
│  main.py (DeepStream Pipeline):                                                                   │
│    nvarguscamerasrc / uridecodebin ──► nvstreammux ──► nvinfer (YOLOv11 TensorRT)                 │
│                                    ──► nvtracker (NvDCF) ──► Python Probes (Speed/ROI/Counts)     │
│                                    ──► nvdsosd ──► MediaMTX RTSP Sink (Branch On-Demand)          │
│  jetson_agent.py (Daemon thường trực):                                                            │
│    Quản lý subprocess main.py • Nhận lệnh MQTT • Auto-stop khi hết video (EOS) • Cooldown an toàn │
└───────────────────────────┬───────────────────────────────────┬───────────────────────────────────┘
                            │ MQTT TLS (8883)                   │ RTSP (8554)
                            ▼                                   ▼
┌────────────────── HiveMQ Cloud Broker ─────────────────┐ ┌──────── MediaMTX Streaming Server ─────────┐
│ Topics:                                                │ │ Cổng: RTSP 8554, WebRTC 8889, HLS 8888        │
│   traffic/{edge_id}/telemetry       (1Hz metric)       │ │ Tự nhận IP LAN máy chủ / Hostname client      │
│   traffic/{edge_id}/heartbeat       (5s trạng thái)    │ └──────────────────────┬────────────────────────┘
│   traffic/{edge_id}/commands        (Web -> Jetson)    │                        │
│   traffic/{edge_id}/command-result  (Jetson -> Web)    │                        │ WebRTC IFrame (<500ms)
└───────────────────────────┬────────────────────────────┘                        │
                            │ MQTT Subscribe                                      │
                            ▼                                                     │
┌────────────────── FastAPI Backend Hub (:8000) ─────────────────┐                 │
│ services/mqtt_service.py: Cập nhật DataStore & Broadcast WSS   │                 │
│ routers/live.py: Điều khiển luồng MediaMTX & Tự nhận diện IP   │                 │
│ routers/remote_control.py: Điều khiển ROI, Video & Pipeline    │                 │
└───────────────────────────┬────────────────────────────────────┘                 │
                            │ WebSocket / REST API (:8000)                        │
                            ▼                                                     │
┌────────────────── WebGIS Frontend Dashboard (:5173) ─────────────────────────────┴─────────────────┐
│ React 18 + TypeScript + Vite + Tailwind CSS                                                       │
│   - WebGISMap.tsx: Bản đồ GIS giám sát camera, tình trạng kẹt xe thời gian thực                   │
│   - RemoteControlModal.tsx: Bảng điều khiển từ xa, vẽ ROI, chọn video/camera, Start/Stop Pipeline │
│   - MediaMTXPlayer.tsx: Trình phát WebRTC/LL-HLS tự động chuẩn hóa hostname theo trình duyệt      │
└───────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Bản Đồ File Trọng Yếu (Core Files Manifest)

| File Đường Dẫn | Vai Trò & Trách Nhiệm Chính |
| :--- | :--- |
| [`main.py`](main.py) | **Edge Pipeline:** Điểm vào DeepStream trên Jetson, nạp YOLOv11 + tracker, gắn probes tính tốc độ qua ma trận Homography, đếm xe, OSD và phát telemetry. |
| [`core/gstreamer_builder.py`](core/gstreamer_builder.py) | **GStreamer Builder:** Cấu hình pipeline phần cứng (NVMM, `nvarguscamerasrc`, `uridecodebin`, `nvstreammux`, `nveglglessink`, nhánh MediaMTX RTSP). |
| [`communication/jetson_agent.py`](communication/jetson_agent.py) | **Edge Daemon:** Chạy nền 24/7, nhận lệnh MQTT, điều khiển vòng đời `main.py`, xử lý kết thúc video (EOS), tự động dọn dẹp camera và bộ nhớ GPU. |
| [`communication/mqtt_client.py`](communication/mqtt_client.py) | **Edge MQTT:** Kết nối HiveMQ Cloud TLS, gửi `telemetry` (1Hz), `heartbeat` (5s), `command-result`. |
| [`analytics/speed_estimator.py`](analytics/speed_estimator.py) | **Đo Tốc Độ:** Ước tính vận tốc thực tế (km/h) từ tọa độ bounding box bottom-center qua biến đổi phối cảnh 4 điểm. |
| [`spatial/roi_manager.py`](spatial/roi_manager.py) | **Quản Lý ROI:** Đọc/ghi cấu hình Detection ROI & Analysis ROI (tọa độ chuẩn hóa `0.0 - 1.0`). |
| [`webgis/backend/main.py`](webgis/backend/main.py) | **FastAPI Core:** Khởi tạo WebSocket manager, nạp SQLite, kích hoạt MQTT worker nền. |
| [`webgis/backend/routers/live.py`](webgis/backend/routers/live.py) | **Live Router:** Bật/tắt On-Demand stream, hàm `get_local_lan_ip()` tự dò IP LAN máy chủ cho RTSP và hostname cho WebRTC. |
| [`webgis/backend/routers/remote_control.py`](webgis/backend/routers/remote_control.py) | **Remote API:** Gửi lệnh qua MQTT (`start_pipeline`, `stop_pipeline`, `capture_preview`, `set_roi_remote`). |
| [`webgis/backend/services/mqtt_service.py`](webgis/backend/services/mqtt_service.py) | **Backend MQTT Bridge:** Lắng nghe topic Jetson, cập nhật node state vào `DataStore` và broadcast ra WebSocket. |
| [`webgis/frontend/src/components/Fleet/RemoteControlModal.tsx`](webgis/frontend/src/components/Fleet/RemoteControlModal.tsx) | **Remote Modal:** 4 bước cấu hình (chọn video/CSI -> lấy frame -> vẽ ROI -> chạy pipeline), Cooldown 2s chống kẹt phần cứng. |
| [`webgis/frontend/src/components/Camera/MediaMTXPlayer.tsx`](webgis/frontend/src/components/Camera/MediaMTXPlayer.tsx) | **Live Player:** Phát WebRTC/LL-HLS, tự động map `window.location.hostname` chống lỗi lệch IP mạng LAN. |

---

## 4. Giao Thức Lệnh MQTT (MQTT Command Protocol)

- **Topic nhận lệnh (Backend ➔ Jetson):** `traffic/{edge_id}/commands`
- **Topic trả kết quả (Jetson ➔ Backend):** `traffic/{edge_id}/command-result`

### Các lệnh hợp lệ (Whitelist):
1. `list_videos`: Quét các file video `.h264`, `.mp4` trong thư mục `Video/`.
2. `capture_preview`: Chụp 1 khung hình (từ video hoặc camera CSI) để Web vẽ ROI.
3. `set_roi_remote`: Lưu tọa độ đa giác ROI mới vào `configs/roi_config.remote.json`.
4. `start_pipeline`: Khởi chạy AI pipeline (`params: {source_type: "file"|"csi", video_name: "...", display: bool}`).
5. `stop_pipeline`: Dừng pipeline an toàn (`SIGINT` giải phóng VRAM và bus camera).
6. `start_live` / `stop_live`: Đóng/mở van GStreamer (`valve`) đẩy luồng RTSP về MediaMTX.

---

## 5. Đặc Thù Phần Cứng & Quy Tắc Bất Di Bất Dịch (Hardware Rules)

1. **Jetson Nano 4GB Shared RAM:**
   - RAM chia sẻ chung giữa OS, CPU và GPU. Tuyệt đối không bật hiển thị màn hình (`display=False / fakesink`) trong môi trường sản xuất để tiết kiệm 25% VRAM và tránh giật lag.
   - Video đầu vào chạy tốt nhất ở chuẩn **FullHD 1080p @ 30 FPS, H.264 Byte-stream (`.h264`)**.
2. **Camera CSI & `nvargus-daemon`:**
   - Cảm biến CSI qua I2C chỉ cho phép 1 tiến trình chiếm dụng độc quyền.
   - Khi bấm **Dừng** hoặc chuyển đổi nguồn video, bắt buộc có **khoảng nghỉ Cooldown 1.5 – 2 giây** để daemon camera giải phóng hoàn toàn bus phần cứng trước khi chạy lệnh mới.
3. **Cơ Chế Hết Video (EOS - End Of Stream):**
   - Video file không bắt buộc loop: Khi chạy hết, DeepStream phát tín hiệu `EOS`.
   - `jetson_agent.py` bắt sự kiện kết thúc bình thường (`code 0`), dọn dẹp sạch sẽ và gửi `stop_pipeline (completed)` về Web để hiện bảng tổng kết (số xe, tốc độ TB), không tự restart.
4. **Mạng & IP Động:**
   - Không fix cứng IP trong code. Phía Web xem stream dùng `window.location.hostname`. Phía Jetson đẩy RTSP dùng IP LAN do `live.py` tự dò qua socket UDP.

---

## 6. Lệnh Vận Hành Nhanh (Cheatsheet)

```bash
# Khởi động toàn bộ WebGIS trên Windows (Auth + Backend + Frontend + MediaMTX):
start_webgis.bat

# Khởi động Agent trên Jetson Nano:
python3 communication/jetson_agent.py

# Khởi chạy Pipeline thủ công bằng lệnh trên Jetson:
python3 main.py --source Video/16.h264 --no-display
python3 main.py --source csi --no-display

# Khóa xung nhịp tối đa trên Jetson (Fix giật lag):
sudo nvpmodel -m 0 && sudo jetson_clocks
```

