# BÁO CÁO RÀ SOÁT HỆ THỐNG EDGE AI – WEBGIS GIAO THÔNG

- **Ngày rà soát:** 04/11/2026
- **Phạm vi:** toàn bộ mã nguồn trong `C:\KLTN\Project` (~23.000 dòng: Edge Jetson, WebGIS backend/auth/frontend, công cụ, tài liệu)
- **Phương pháp:** đọc mã tĩnh và đối chiếu "hợp đồng" dữ liệu giữa các khối (MQTT, REST, file IPC). **Chưa chạy thử trên Jetson.** Những mục cần xác nhận trên thiết bị được đánh dấu *(cần kiểm chứng)*.
- **Trạng thái:** đã xử lý ngày 04/11/2026. Xem kết quả tại [BAO_CAO_SUA_CHUA_HE_THONG.md](BAO_CAO_SUA_CHUA_HE_THONG.md).

---

## 1. Kết luận nhanh

| Câu hỏi | Trả lời |
|---|---|
| Phạm vi chức năng có đủ cho khóa luận không? | **Đủ, thậm chí rộng.** Có Edge AI (YOLO + DeepStream + NvDCF), đo tốc độ bằng homography, phân loại ùn tắc 2 phương án, dự báo, WebGIS thời gian thực, live stream, điều khiển từ xa, phân quyền. |
| Hệ thống đã "ổn" chưa? | **Chưa.** Có **2 lỗi nghiêm trọng** làm hỏng hẳn một chức năng (ảnh bằng chứng ùn tắc không lên được WebGIS; agent có thể làm chết camera của pipeline) và **6 lỗi mức cao** ảnh hưởng trực tiếp tới số liệu hoặc khả năng triển khai. |
| Đã đủ để bảo vệ chưa? | **Chưa.** Thiếu lớn nhất là **bằng chứng thực nghiệm**: cả 3 bảng kết quả trong báo cáo tiến độ (mAP, FPS, sai số tốc độ) vẫn để trống, benchmark v1/v2 mới chạy trên dữ liệu tổng hợp, và gần như chưa có kiểm thử tự động. |

**Đánh giá chung:** kiến trúc tốt và tài liệu nhiều. Tuy vậy, cần khoảng **3–5 ngày sửa lỗi** cộng **1–2 tuần thu thập số liệu** thì mới sẵn sàng bảo vệ.

---

## 2. Danh sách vấn đề

Mức độ: 🔴 Nghiêm trọng (hỏng chức năng) · 🟠 Cao (sai số liệu hoặc hỏng khi triển khai) · 🟡 Trung bình · ⚪ Thấp

### 2.1. 🔴 Nghiêm trọng

#### C1. Ảnh bằng chứng ùn tắc từ Jetson luôn bị backend từ chối (HTTP 401)
- **Vị trí:** [snap/snapshot_service.py:476](../snap/snapshot_service.py) và [:509](../snap/snapshot_service.py) ↔ [webgis/backend/routers/snapshots.py:50-74](../webgis/backend/routers/snapshots.py)
- **Mô tả:** Jetson gửi `Authorization: Bearer <EDGE_TOKEN>`. Backend chỉ chấp nhận EDGE_TOKEN qua header `X-Edge-Token`. Header `Bearer` thì backend coi là **JWT của nhân viên** và giải mã bằng `JWT_SECRET`, mà EDGE_TOKEN không phải JWT nên luôn thất bại.
- **Kịch bản:** đường chuyển sang CONGESTED đủ 15 s → Jetson chụp ảnh → upload → 401 → ảnh nằm lại trong outbox và cứ 15 s thử lại → WebGIS không bao giờ có ảnh bằng chứng. Lỗi đã có từ trước bản backup 30/10.
- **Hướng sửa:** gửi thêm `X-Edge-Token` từ Jetson, hoặc cho backend chấp nhận EDGE_TOKEN trong `Bearer`. Sửa 1 dòng.

#### C2. Agent có thể tự mở camera và restart `nvargus-daemon` khi `main.py` đang chạy
- **Vị trí:** [communication/jetson_agent.py:252-270](../communication/jetson_agent.py), [:651-655](../communication/jetson_agent.py), [:561-581](../communication/jetson_agent.py)
- **Mô tả:**
  1. `capture_preview` chỉ coi pipeline "đang chạy" nếu đó là **tiến trình con của agent**. `main.py` chạy bằng tay, hoặc do agent cũ để lại, đều không được tính.
  2. Mở camera thất bại thì agent chạy `sudo systemctl restart nvargus-daemon`, làm chết phiên Argus của pipeline.
  3. `capture_preview` **không dùng `pipeline_lock`**. Mỗi lệnh MQTT chạy trên một luồng riêng ([command_router.py](../communication/command_router.py)), nên `capture_preview` và `start_csi` có thể chạy song song và tranh nhau camera.
- **Kịch bản:** đây là nguyên nhân khả dĩ nhất của hiện tượng "cửa sổ python3 hiện nhưng không nhận diện" đã báo trước đó.
- **Hướng sửa:** xác định trạng thái pipeline bằng cách quét tiến trình (đã có sẵn trong `make_request_status_handler`) hoặc bằng file khóa; dùng `pipeline_lock` cho mọi thao tác camera; không restart nvargus khi còn `main.py` sống. Thêm khóa chạy một bản cho `main.py` (xem M7).

### 2.2. 🟠 Cao

#### H1. Lấy preview từ pipeline đang chạy luôn thất bại
- **Vị trí:** [main.py:934-948](../main.py)
- **Mô tả:** `pyds.get_nvds_buf_surface()` được gọi trong probe ở **đầu ra của tracker**, nơi buffer có định dạng **NV12**. Hàm này chỉ đọc được **RGBA**, nên luôn báo lỗi, và agent chờ 2 s rồi báo timeout.
- **Hệ quả:** khi pipeline đang chạy CSI, WebGIS không lấy được ảnh để vẽ ROI. Người dùng phải dừng pipeline trước, mà dừng thì lại dễ gặp C2.
- **Hướng sửa:** chuyển phần xử lý preview sang probe ở `osd` src pad (RGBA). Snapshot đang dùng đúng pad này.

#### H2. Bộ đếm xe theo lớp bị "trôi" khi YOLO đổi nhãn của một track
- **Vị trí:** [analytics/presence_counter.py:76](../analytics/presence_counter.py), [:85](../analytics/presence_counter.py), [:99-101](../analytics/presence_counter.py), [:117-119](../analytics/presence_counter.py)
- **Mô tả:** khi xác nhận vào ROI, bộ đếm tăng theo **lớp lúc vào** (ví dụ `motorbike`). Nhưng `state['class_name']` được cập nhật mỗi frame, nên khi xe rời đi bộ đếm lại trừ theo **lớp mới** (ví dụ `bicycle`, sau đó bị kẹp về 0).
- **Kịch bản:** nhãn nhấp nháy giữa motorbike và bicycle, hoặc car và truck, là chuyện rất thường gặp → `current_by_class['motorbike']` tăng mãi → **xe ma** cộng dồn theo thời gian → mật độ PCE tăng → báo SLOW/CONGESTED giả khi chạy lâu (24/7).
- **Hướng sửa:** đếm lại từ các track đang `confirmed` mỗi lần gọi `snapshot()`, hoặc trừ theo lớp đã dùng lúc cộng.

#### H3. Các bộ lọc tin cậy cho tính tốc độ chỉ hoạt động khi bật chế độ debug
- **Vị trí:** [main.py:818-831](../main.py) và [:871-892](../main.py)
- **Mô tả:** `obj_diagnostics`, tức độ tin cậy detector/tracker và diện tích bbox, **chỉ được điền khi bật `--debug-diagnostics`**. Ở chế độ thường thì `det_conf`, `trk_conf`, `area` đều là `None`, nên `--min-detector-confidence`, `--min-tracker-confidence`, `--max-bbox-area-change` **không có tác dụng**.
- **Hệ quả:** số liệu tốc độ khi demo khác với khi debug. Nếu báo cáo có mô tả các bộ lọc này thì mô tả đó đang không đúng với thực tế chạy.
- **Hướng sửa:** luôn điền phần dữ liệu tối thiểu (conf, area); chỉ phần in bảng chẩn đoán mới phụ thuộc cờ debug.

#### H4. API lịch sử bị lỗi 500 khi trong ngày có phút đường vắng
- **Vị trí:** [webgis/backend/routers/history.py:20-27](../webgis/backend/routers/history.py)
- **Mô tả:** `avg_speed_kmh` được lưu NULL khi đường vắng (chủ ý, theo [data_store.py:908](../webgis/backend/services/data_store.py)). Nhưng `min(speeds)` và `sum(speeds)` không lọc `None` → `TypeError` → biểu đồ lịch sử không tải được.
- **Hướng sửa:** lọc `r["avg_speed_kmh"] is not None`.

#### H5. Chạy bằng Docker thì backend không dùng chung `JWT_SECRET` với auth-service
- **Vị trí:** [webgis/backend/config.py:16-28](../webgis/backend/config.py), [docker-compose.yml](../docker-compose.yml) (service `backend`)
- **Mô tả:** backend lấy `JWT_SECRET` từ `../auth-service/.env`. Trong container backend không có file này. File `.env` gốc và `webgis/backend/.env` cũng không có `JWT_SECRET`. Kết quả là backend dùng khóa mặc định, khác khóa của auth-service.
- **Hệ quả:** khi triển khai lên VPS bằng Docker, **mọi API nhân viên đều trả 401** và WebSocket coi mọi người là khách. Chạy native trên Windows thì không lỗi, nên dễ không phát hiện ra.
- **Hướng sửa:** đặt `JWT_SECRET` trong một nguồn chung (file `.env` gốc) cho cả hai service; backend báo lỗi và dừng khởi động nếu thiếu khóa.

#### H6. Thuật toán v2 tính cả xe đỗ cố định vào Dwell-Time
- **Vị trí:** [analytics/traffic_classifier_v2.py:341-358](../analytics/traffic_classifier_v2.py) ↔ [analytics/traffic_classifier.py:446-449](../analytics/traffic_classifier.py)
- **Mô tả:** lớp cha loại xe "chưa từng di chuyển" khỏi `stopped_ratio`, nhưng v2 vẫn đưa các xe đó vào `max_dwell_s` và `stopped_dwell_max_s`. Một xe đỗ lề trong ROI làm `max_dwell` tăng mãi.
- **Kịch bản (midblock):** có ≥5 xe trong ROI và một xe đỗ quá 15 s → luôn ra **ít nhất SLOW**, và thành **CONGESTED** khi tỷ lệ dừng ≥ 25%. Ở nút giao (signalized), xe đỗ quá 55 s đẩy hệ thống vào nhánh CONGESTED/SLOW.
- **Hướng sửa:** chỉ tính dwell cho các track có `has_moved=True` và không nằm trong vùng loại trừ.

### 2.3. 🟡 Trung bình

| ID | Vấn đề | Vị trí | Hệ quả / Hướng sửa |
|---|---|---|---|
| M1 | **Ngưỡng điểm → trạng thái không thống nhất** giữa các nơi | [traffic_classifier.py:598-603](../analytics/traffic_classifier.py) (dự báo dùng 60/30); [WebGISMap.tsx:483-486](../webgis/frontend/src/components/Map/WebGISMap.tsx) (popup dùng 60/35); các nơi khác dùng 65/35; v1 `slow_max_score=65` trùng với `congested_min_score=65` | Dự báo 62 điểm ra "CONGESTED" trong khi thang hiện tại là SLOW; popup tô đỏ ở 60–64. Cần **một nguồn ngưỡng duy nhất**. Hội đồng dễ hỏi điểm này. |
| M2 | **Vùng loại trừ (exclusion_polygons) không bao giờ được áp dụng** | [traffic_classifier.py:433-444](../analytics/traffic_classifier.py) | Code cần `presence_snapshot['track_positions']`, nhưng `RoiPresenceCounter.snapshot()` không trả trường này. Tính năng tồn tại trên giấy nhưng không chạy. |
| M3 | **Telemetry bỏ mất các trường của v2** | [communication/mqtt_client.py:295-321](../communication/mqtt_client.py) | `max_dwell_s`, `dwell_time_avg_s`, `is_incident`, `algorithm_version`, `traffic_context` không được gửi lên, nên WebGIS không hiển thị được sự cố hay phiên bản thuật toán. |
| M4 | **Trạng thái `pipeline_running` trong heartbeat chỉ dựa trên tiến trình con của agent** | [jetson_agent.py:1081-1088](../communication/jetson_agent.py) | Chạy `main.py` bằng tay thì heartbeat báo "không chạy" dù vẫn có telemetry. Backend đang bù bằng mẹo kiểm tra "có telemetry trong 15 s" ([mqtt_service.py:218-232](../webgis/backend/services/mqtt_service.py)). Gốc rễ chung với C2. |
| M5 | **Code chết và có lỗi trong `main.py`** | [main.py:629-673](../main.py), [:706-720](../main.py); [mqtt_client.py:659](../communication/mqtt_client.py) | Tiến trình pipeline chỉ nhận các lệnh live, nên handler `reload_config` và `capture_test_snapshot` trong `main.py` không bao giờ chạy. Ngoài ra `reload_config` gọi `presence_counter.reset()`, **hàm này không tồn tại**. Nên xóa hoặc sửa để tránh bị hỏi. |
| M6 | **Đường dẫn engine tương đối bị kiểm tra theo CWD**, còn nvinfer lại tìm theo thư mục chứa config | [core/gstreamer_builder.py:324-329](../core/gstreamer_builder.py) | Có thể khiến nvinfer build lại engine 10–20 phút, màn hình đen *(cần kiểm chứng)*. Nên ghi đường dẫn tuyệt đối vào config. |
| M7 | **Không có khóa chạy một bản cho `main.py`** | [main.py](../main.py) | Chạy 2 pipeline cùng lúc thì camera báo busy. Nên dùng `fcntl.flock` trên file `.pipeline.lock`. |
| M8 | **Hạn sống lệnh (TTL) 30 s phụ thuộc đồng hồ Jetson** | [mqtt_client.py:672-686](../communication/mqtt_client.py), [command_router.py:155-170](../communication/command_router.py) | Đồng hồ Jetson lệch quá 30 s (chưa đồng bộ NTP, chạy offline) thì **mọi lệnh từ WebGIS bị báo "expired"**. Cần bật NTP và ghi chú trong hướng dẫn triển khai. |
| M9 | **"stopped_dwell" thực ra đo thời gian từ lúc vào ROI**, không phải từ lúc dừng | [traffic_classifier_v2.py:114-119](../analytics/traffic_classifier_v2.py) | Xe đi chậm 25 s rồi dừng 1 s đã bị tính là "dừng 26 s". Cần sửa định nghĩa trong code, hoặc mô tả đúng trong báo cáo. |
| M10 | **Dự báo hồi quy chạy lại trên toàn bộ lịch sử ở mỗi frame** | [traffic_classifier.py:524-529](../analytics/traffic_classifier.py), [:559-571](../analytics/traffic_classifier.py) | 900 s × ~25 fps ≈ 22.000 điểm được xử lý lại mỗi frame trong probe GStreamer. Có thể làm giảm FPS và tăng tải CPU trên Nano *(cần kiểm chứng)*. Nên lấy mẫu 1 Hz. |

### 2.4. 🔐 Bảo mật

| ID | Vấn đề | Vị trí | Hướng sửa |
|---|---|---|---|
| S1 | Mật khẩu MQTT `12345678`, token `dev-edge-token` và `JWT_SECRET` mặc định được **viết cứng trong ~12 file** | ví dụ [main.py:78-83](../main.py), [mqtt_client.py:89](../communication/mqtt_client.py), [backend/config.py:38,48](../webgis/backend/config.py), [jwt.js:3](../webgis/auth-service/src/utils/jwt.js) | Bỏ giá trị mặc định; thiếu biến môi trường thì dừng khởi động. **Đổi mật khẩu HiveMQ** vì giá trị cũ đã lộ trong code. |
| S2 | Phân quyền ảnh snapshot không nhất quán: `/api/v1/snapshots` yêu cầu nhân viên, nhưng **`/api/v1/history/snapshots` công khai** cùng dữ liệu | [routers/history.py:32-36](../webgis/backend/routers/history.py) ↔ [routers/snapshots.py:253](../webgis/backend/routers/snapshots.py) | Ảnh có thể chứa biển số và khuôn mặt, nên cần thống nhất chính sách quyền truy cập. |
| S3 | `CORS_ORIGIN=*`, frontend Docker chạy `vite dev`, `ALLOW_PUBLIC_REGISTER` mặc định cho phép | [docker-compose.yml](../docker-compose.yml), [frontend/Dockerfile](../webgis/frontend/Dockerfile) | Sửa khi làm bản production (đã nêu trong phương án triển khai VPS). |
| S4 | MediaMTX không xác thực khi publish: ai biết IP cũng đẩy được luồng giả | [deploy/mediamtx/mediamtx.yml](../deploy/mediamtx/mediamtx.yml) | Thêm `authInternalUsers`. |
| S5 | Backend tin `role` trong JWT mà không đối chiếu CSDL (auth-service thì có đối chiếu); token sống 7 ngày | [services/auth_middleware.py](../webgis/backend/services/auth_middleware.py) | Mức thấp. Chỉ cần nêu là giới hạn đã biết, hoặc rút ngắn thời hạn token. |

### 2.5. ⚪ Thấp và tổ chức mã nguồn

| ID | Vấn đề | Đề xuất |
|---|---|---|
| L1 | **Dự án chưa dùng git.** Có thư mục `_backup_truoc_khi_sua_*`, thư mục rỗng `edge-ai-gan-full`, và agent còn tìm `main3.py` | `git init` ngay, commit trạng thái hiện tại, xóa backup và thư mục rỗng. Hội đồng thường hỏi về quản lý phiên bản. |
| L2 | `_seen_track_ids` tăng mãi không dọn ([traffic_classifier.py:345,366](../analytics/traffic_classifier.py)) | Chạy 24/7 thì rò bộ nhớ chậm. Nên dọn theo cửa sổ thời gian. |
| L3 | Tốc độ vào ROI (entry rate) dùng đồng hồ thật, các chỉ số khác dùng thời gian của luồng video ([traffic_classifier.py:361,498](../analytics/traffic_classifier.py)) | Khi chạy video file nhanh hoặc chậm hơn thời gian thực, các chỉ số bị lệch nhau. Nên dùng chung `event_time`. |
| L4 | Backend ghi file JSON trạng thái và mở SQLite ở **mỗi** bản tin telemetry | Ổn với vài node. Cần nêu trong phần "giới hạn mở rộng". |
| L5 | **Kiểm thử tự động gần như bằng 0** (chỉ có `webgis/tools/test_heat_simulation.py`) | Các module `analytics/` đã được thiết kế để test được trên PC. Nên viết unit test cho tốc độ, đếm ROI, phân loại v1/v2 và đưa kết quả vào chương đánh giá. |

---

## 3. Đánh giá mức sẵn sàng cho khóa luận

### 3.1. Chức năng

| Chức năng | Trạng thái | Ghi chú |
|---|---|---|
| Nhận diện YOLO11 + DeepStream FP16 trên Jetson Nano | ✅ Đã có | Chưa có số liệu mAP/FPS |
| Theo dõi đối tượng NvDCF / IOU | ✅ | |
| Đo tốc độ bằng homography + hồi quy | ✅ | Thuật toán tốt; **chưa có kiểm chứng thực địa**; bộ lọc bị H3 |
| Đếm xe trong ROI có hysteresis | ⚠️ | Lỗi H2 (xe ma khi chạy lâu) |
| Phân loại ùn tắc v1 / v2 | ⚠️ | H6, M1, M9; ngưỡng là giả định, chưa hiệu chỉnh |
| Dự báo 5/10 phút | ⚠️ | Là **ngoại suy tuyến tính** trên điểm số (code đã ghi chú đúng). Cần trình bày trung thực, không gọi là "AI dự báo". |
| Ảnh bằng chứng ùn tắc | ❌ | **C1**: không lên được WebGIS |
| WebGIS bản đồ thời gian thực | ✅ | |
| Live stream (MediaMTX, WebRTC/HLS) | ✅ | Cần S4 khi đưa lên internet |
| Điều khiển từ xa (start/stop, ROI, preview) | ⚠️ | C2, H1 |
| Đăng nhập, phân quyền | ✅ | S2, S5 |
| Lịch sử, playback | ⚠️ | H4 |
| Triển khai cloud / VPS | ⚠️ | H5, S1, S3 |

### 3.2. Bằng chứng thực nghiệm (điểm yếu lớn nhất)

| Hạng mục hội đồng sẽ hỏi | Hiện trạng | Cần làm |
|---|---|---|
| Độ chính xác mô hình (Precision/Recall/mAP theo lớp) | ❌ Bảng 1 trong [BAO_CAO_TIEN_DO](BAO_CAO_TIEN_DO_NGHIEN_CUU_EDGE_AI.md) còn trống | Lấy từ kết quả huấn luyện (`results.csv`, confusion matrix của Ultralytics) trên tập validation |
| Hiệu năng trên Nano (FPS, độ trễ, GPU/RAM, nhiệt độ) | ❌ Bảng 2 trống | Chạy `tegrastats` cùng log FPS của pipeline, 10–15 phút cho mỗi cấu hình |
| Sai số tốc độ (MAE) | ❌ Bảng 3 trống | Cho xe chạy thử, so với GPS điện thoại (≥10 lượt × 3 dải tốc độ), đối chiếu bằng `tools/validate_calibration.py` |
| Độ chính xác phân loại ùn tắc v1 vs v2 | ⚠️ Mới có kịch bản **tổng hợp** ([tools/compare_congestion_models.py](../tools/compare_congestion_models.py)) | Quay video thật, gán nhãn tay FREE/SLOW/CONGESTED theo khoảng thời gian, ra confusion matrix và F1 cho v1 và v2 |
| Kiểm thử phần mềm | ❌ | Unit test cho `analytics/`, kèm bảng kết quả pass/fail |
| Dữ liệu demo | ❌ Thư mục `Video/` đang rỗng trên máy này | Chuẩn bị 2–3 video đã quay để demo dự phòng khi camera CSI có sự cố |

---

## 4. Lộ trình đề xuất

| Giai đoạn | Nội dung | Ước lượng |
|---|---|---|
| **P0 – An toàn mã nguồn** | `git init` + commit hiện trạng (L1) | 0,5 giờ |
| **P1 – Sửa lỗi chặn demo** | C1, C2 + M7, H1, H4, H5 | 1–2 ngày |
| **P2 – Sửa lỗi ảnh hưởng số liệu** | H2, H3, H6, M1, M2, M3, M5, M9; viết unit test cho `analytics/` (L5) | 2–3 ngày |
| **P3 – Thu thập số liệu** (làm song song với P2) | 3 bảng thực nghiệm + đánh giá v1/v2 trên video thật | 1–2 tuần (phụ thuộc thực địa) |
| **P4 – Bảo mật và triển khai** | S1–S4, M8, bản production cho VPS | 1–2 ngày |
| **P5 – Hiệu năng** | M10, L2, L3 (sau khi đo FPS ở P3 để có số liệu trước/sau) | 0,5–1 ngày |

P3 nên bắt đầu sớm nhất vì phụ thuộc thời tiết, địa điểm và thiết bị. Riêng **phần quay video thô** có thể làm ngay, trước khi sửa code, rồi phân tích lại sau khi đã sửa.

---

## 5. Điểm mạnh nên nhấn mạnh khi bảo vệ

- Kiến trúc Edge – Cloud tách bạch: AI chạy ở biên, chỉ gửi số liệu đã xử lý, tiết kiệm băng thông.
- Đo tốc độ bằng homography kèm **hồi quy tuyến tính trên lịch sử track**, lọc spike và chống trôi xe đỗ. Các module thuật toán không phụ thuộc DeepStream nên kiểm thử được độc lập.
- Phân loại ùn tắc **theo ngữ cảnh** (nút giao có đèn hoặc đoạn giữa), có quy đổi **PCE** theo đặc thù xe máy Việt Nam.
- Cơ chế bền vững: outbox offline cho ảnh, hàng đợi MQTT khi mất mạng, watchdog tự khởi động lại pipeline, zero-touch provisioning theo MAC.
- WebGIS đầy đủ: bản đồ, thời gian thực qua WebSocket, phân quyền, lịch sử, live stream theo yêu cầu.

---

## 6. Các điểm cần thảo luận

1. **Hạn bảo vệ / nộp báo cáo** là khi nào? Từ đó quyết định làm hết P1–P5 hay chỉ P0–P3.
2. Thứ tự sửa: đề xuất **P0 → P1 → P2**. Bạn có muốn ưu tiên khác không?
3. Có giữ **cả v1 và v2** không? Đề xuất là giữ, vì đó chính là thí nghiệm so sánh của khóa luận, nhưng ghi rõ v2 là phương án chính.
4. Phần **dự báo 5/10 phút**: giữ là "ngoại suy xu hướng" và trình bày trung thực, hay nâng cấp? Đề xuất là giữ và đưa vào mục hướng phát triển.
5. Bạn còn **kết quả huấn luyện YOLO** (thư mục `runs/` có `results.csv`, `confusion_matrix.png`) không? Nếu còn thì Bảng 1 lấp được ngay.
