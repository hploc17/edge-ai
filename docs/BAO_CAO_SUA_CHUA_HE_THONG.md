# BÁO CÁO SỬA CHỮA HỆ THỐNG EDGE AI – WEBGIS GIAO THÔNG

- **Ngày thực hiện:** 04/11/2026
- **Căn cứ:** [BAO_CAO_RA_SOAT_HE_THONG.md](BAO_CAO_RA_SOAT_HE_THONG.md) (rà soát cùng ngày)
- **Mốc trước khi sửa:** commit git `fdd2185` ("Baseline: hiện trạng trước khi sửa…"). Xem toàn bộ thay đổi bằng lệnh `git diff fdd2185`.
- **Quy mô thay đổi:** 27 file sửa (+640 / −382 dòng), thêm 2 file test và `.gitattributes`. **Chưa commit**, để bạn xem lại trước.

---

## 1. Tóm tắt

| Nhóm | Số mục | Đã sửa | Còn lại |
|---|---|---|---|
| 🔴 Nghiêm trọng (C1–C2) | 2 | 2 | 0 |
| 🟠 Cao (H1–H6) | 6 | 6 | 0 |
| 🟡 Trung bình (M1–M10) | 10 | 10 | 0 |
| 🔐 Bảo mật (S1–S5) | 5 | 2 (S1, S2) | S3, S4, S5: làm khi triển khai VPS |
| ⚪ Thấp (L1–L5) | 5 | 4 (L1, L2, L3, L5) | L4: ghi nhận là giới hạn |

**Kiểm chứng trên máy phát triển (Windows, Python 3.11):**
- **28/28 unit test đạt** (`python -m unittest discover -s tests -v`).
- Toàn bộ file Python biên dịch được. Frontend qua `tsc` không lỗi. Các file JS của auth-service qua `node --check`.
- Đã import backend và gọi thử API bằng `TestClient`: `/history/timeline` trả 200; `/history/snapshots` với khách trả 401; upload sai token trả 401.
- Đã **tái hiện lỗi trên mã cũ rồi so với mã mới**:

| Kịch bản | Mã cũ (`fdd2185`) | Mã mới |
|---|---|---|
| 50 xe đi qua ROI, YOLO đổi nhãn motorbike ↔ bicycle, ROI đã trống | `current_total = 11` (**11 xe ma**) | `0` |
| 1 xe đỗ chưa từng di chuyển + 5 xe chạy 32 km/h, đoạn không đèn, 60 s | **SLOW**, score 35 | **FREE** |
| Số điểm lưu cho dự báo sau 15 phút ở 25 fps | ~22.500 điểm, hồi quy lại mỗi frame | ≤ 900 điểm (1 Hz), hồi quy tối đa 1 lần/giây |

> ⚠️ **Chưa chạy trên Jetson Nano.** Các phần dùng DeepStream/GStreamer (probe preview, khóa camera, dừng tiến trình) mới được kiểm tra bằng biên dịch và đọc mã. Danh sách kiểm tra trên thiết bị nằm ở **Mục 5**.

---

## 2. Chi tiết từng mục

### 2.1. 🔴 Nghiêm trọng

| ID | Đã sửa thế nào | File | Kiểm chứng |
|---|---|---|---|
| **C1** Ảnh bằng chứng bị 401 | Jetson gửi thêm header `X-Edge-Token`. Backend gom việc xác thực thiết bị về **một hàm chung** `verify_edge_token()`, nhận cả `X-Edge-Token` lẫn `Authorization: Bearer <EDGE_TOKEN>` (tương thích bản Jetson cũ), so sánh hằng thời gian. Backend chưa cấu hình `EDGE_TOKEN` thì từ chối mọi upload, không còn rơi về token mặc định. | `snap/snapshot_service.py`, `webgis/backend/services/auth_middleware.py`, `routers/snapshots.py`, `routers/remote_control.py` | `TestSnapshotUploadAuth` (4 test) |
| **C2** Agent làm chết camera của pipeline | (1) Agent coi pipeline là **đang chạy** nếu có tiến trình con của nó, **hoặc** khóa `.pipeline.lock` đang bị giữ, **hoặc** có `main.py` của dự án chạy ngoài (quét bằng psutil, so đúng đường dẫn `main.py` của dự án). (2) `capture_preview` kiểm tra trạng thái và mở camera **dưới cùng `pipeline_lock`** với start/stop. (3) **Không bao giờ restart `nvargus-daemon`** khi còn pipeline giữ camera. (4) `start_pipeline` và `stop_pipeline` dừng `main.py` chạy tay bằng **SIGINT → SIGTERM → SIGKILL** (trước đây gửi SIGTERM ngay). (5) Bỏ việc tìm `main3.py`. | `communication/jetson_agent.py` | Smoke test helper trên PC; **cần kiểm tra trên Jetson** |

### 2.2. 🟠 Cao

| ID | Đã sửa thế nào | File | Kiểm chứng |
|---|---|---|---|
| **H1** Preview luôn lỗi khi pipeline chạy | Chuyển việc chụp preview sang probe ở **sink pad của `nvdsosd`**, nơi buffer là RGBA. Ảnh lấy ra là ảnh **sạch, chưa vẽ OSD**, tiện cho việc vẽ ROI. Có kiểm tra caps RGBA. Thời gian agent chờ ảnh tăng từ 2 s lên 4 s. | `main.py`, `jetson_agent.py` | **Cần kiểm tra trên Jetson** |
| **H2** Xe ma khi đổi nhãn | Mỗi track lưu phiếu bầu lớp (Counter). Số đếm theo lớp được **tính lại từ các track đang confirmed** ở mỗi lần `snapshot()`, lớp lấy theo đa số phiếu. Không còn biến đếm cộng/trừ dễ lệch. Thêm `reset()`, `track_positions`, `track_classes`. | `analytics/presence_counter.py` | `TestPresenceCounter` (6 test), tái hiện ở bảng Mục 1 |
| **H3** Bộ lọc tin cậy chỉ chạy khi debug | Luôn thu thập độ tin cậy detector/tracker và diện tích bbox. Chỉ phần **in bảng chẩn đoán** còn phụ thuộc `--debug-diagnostics`. | `main.py` | Đọc mã; cần Jetson để đo ảnh hưởng |
| **H4** API lịch sử lỗi 500 | Bỏ qua bản ghi có `avg_speed_kmh = NULL` khi thống kê. | `routers/history.py` | `TestHistoryTimeline`, TestClient trả 200 |
| **H5** Lệch `JWT_SECRET` khi chạy Docker | `config.py` là nguồn duy nhất của `JWT_SECRET`/`EDGE_TOKEN`; `auth_middleware` và `websocket_manager` import từ đó. Backend **dừng khởi động với thông báo rõ ràng** nếu thiếu `JWT_SECRET`. `docker-compose.yml` mount `auth-service/.env` vào container backend. Sửa thêm: `config.py` nạp **tất cả** file `.env` (backend → webgis → gốc) thay vì dừng ở file đầu tiên, vì `MQTT_PASS`/`EDGE_TOKEN` chỉ có trong `.env` gốc. | `webgis/backend/config.py`, `auth_middleware.py`, `websocket_manager.py`, `docker-compose.yml` | Import backend thành công; cần thử `docker compose up` |
| **H6** v2 tính xe đỗ vào dwell | (1) Phân loại dùng **trung vị** thời gian lưu và trung vị thời gian dừng, nên một xe ngoại lai không quyết định trạng thái cả đoạn; giá trị max vẫn được gửi lên để giám sát. (2) Tập "xe đang dừng" dùng **cùng định nghĩa** với `stopped_ratio` của lớp cha (đã đo tốc độ, < 5 km/h, `has_moved`). (3) Bỏ các xe trong vùng loại trừ. | `analytics/traffic_classifier_v2.py` | `TestContextAwareV2` (4 test), tái hiện ở bảng Mục 1 |

**Về H6:** tôi chọn dùng trung vị thay vì loại hẳn xe "chưa từng di chuyển" khỏi dwell. Lý do: trong kẹt xe nặng, xe bò < 3 km/h có thể không bao giờ đạt điều kiện `has_moved`. Nếu loại hẳn các xe này, hệ thống sẽ báo FREE đúng lúc kẹt nhất. Trung vị vừa chịu được một xe đỗ đơn lẻ, vừa vẫn ra CONGESTED khi **đa số** xe dừng lâu (đã có test `test_long_queue_becomes_congested_midblock`).

### 2.3. 🟡 Trung bình

| ID | Đã sửa thế nào | File |
|---|---|---|
| **M1** Ngưỡng không thống nhất | Một thang chung `CONGESTION_THRESHOLDS` kèm hàm `status_from_score()`: FREE 0–34, SLOW 35–64, CONGESTED 65–100. Dự báo dùng hàm này (trước dùng 60/30). v1 `slow_max_score` 65 → 64. Popup bản đồ 60 → 65. Test `TestThresholds` khẳng định điểm và nhãn không bao giờ mâu thuẫn. | `traffic_classifier.py`, `WebGISMap.tsx` |
| **M2** Vùng loại trừ không chạy | `RoiPresenceCounter.snapshot()` trả thêm `track_positions` và `track_classes`. `TrafficAnalyzer` loại xe trong vùng khỏi **số đếm, mật độ, tốc độ, tỷ lệ dừng** và báo `excluded_vehicle_count`. `main.py` không còn ghi đè số đếm bằng số chưa loại trừ. | `presence_counter.py`, `traffic_classifier.py`, `main.py` |
| **M3** Telemetry thiếu trường v2 | Gửi thêm `algorithm_version`, `traffic_context`, `is_incident`, `excluded_vehicle_count`, `dwell_time_avg_s`, `median_dwell_s`, `max_dwell_s`, `stopped_dwell_max_s`, `stopped_dwell_median_s`. Backend vốn chuyển nguyên payload cho frontend qua WebSocket, nên các trường này đã có sẵn ở frontend để hiển thị. | `communication/mqtt_client.py` |
| **M4** Heartbeat sai khi chạy tay | `pipeline_running` trong heartbeat và cơ chế nhường lệnh live dùng chung `_is_pipeline_running()` (C2). | `jetson_agent.py` |
| **M5** Code chết trong `main.py` | Xóa các handler `get_health`, `request_status`, `reload_config`, `capture_test_snapshot` trong tiến trình pipeline, vì tiến trình này chỉ nhận lệnh live; agent đã xử lý các lệnh kia. Thêm `RoiPresenceCounter.reset()` còn thiếu. | `main.py`, `presence_counter.py` |
| **M6** Đường dẫn engine tương đối | `ensure_infer_config` hiểu đường dẫn **theo thư mục chứa file config** (giống nvinfer) và ghi lại thành đường dẫn tuyệt đối. | `core/gstreamer_builder.py` (test `TestInferConfigPaths`) |
| **M7** Hai `main.py` cùng lúc | `main.py` giữ khóa `fcntl.flock` trên `.pipeline.lock` suốt vòng đời; bản thứ hai thoát với **mã 3** kèm thông báo rõ. Watchdog của agent **không tự khởi động lại** khi gặp mã 3. Trên Windows bỏ qua khóa. | `main.py`, `jetson_agent.py` |
| **M8** TTL lệnh phụ thuộc đồng hồ Jetson | Hàm chung `command_expiry()`: lệch đồng hồ **> 600 s** được hiểu là Jetson chưa đồng bộ NTP, nên **chấp nhận lệnh và in cảnh báo** thay vì từ chối mọi lệnh. An toàn vì client dùng `clean_session=True` và lệnh không retain, broker không giao lại lệnh cũ. | `mqtt_client.py`, `command_router.py` (test `TestCommandTtl`) |
| **M9** "stopped_dwell" đo từ lúc vào ROI | Thời gian dừng giờ đo **từ lúc xe bắt đầu dừng**; xe chạy lại thì đặt lại mốc. | `traffic_classifier_v2.py` (test `test_stop_duration_counts_from_stop_not_entry`) |
| **M10** Dự báo hồi quy mỗi frame | Lịch sử điểm lấy mẫu **1 Hz**; kết quả dự báo được lưu đệm và chỉ tính lại khi có mẫu mới. | `traffic_classifier.py` (test `test_forecast_history_sampled_at_1hz`) |

### 2.4. 🔐 Bảo mật

| ID | Trạng thái | Chi tiết |
|---|---|---|
| **S1** Mật khẩu/token viết cứng | ✅ Đã gỡ khỏi **mã nguồn** | Bỏ `12345678`, `dev-edge-token` và JWT mặc định ở 14 file. Thiếu biến thì: backend và auth-service **dừng khởi động**; Jetson in cảnh báo. Các công cụ `simulate_edge.py`, `test_heat_simulation.py` tự nạp `.env` gốc. File `.env.example` dùng `CHANGE_ME`. |
| | ⚠️ **Bạn cần tự làm** | Các file `.env` thật **vẫn đang dùng đúng các giá trị đã lộ** (mật khẩu MQTT `12345678`, `EDGE_TOKEN=dev-edge-token`, `JWT_SECRET` mặc định). Tôi không tự đổi, vì đổi một phía sẽ làm Jetson mất kết nối. Xem Mục 4. |
| **S2** Ảnh snapshot công khai qua `/history/snapshots` | ✅ | Chỉ Staff được xem, giống `/api/v1/snapshots`. Frontend tải biểu đồ và ảnh **độc lập** (`Promise.allSettled`), nên khách vẫn xem được biểu đồ lịch sử. |
| **S3** CORS / Docker frontend chạy dev / mở đăng ký | ⏳ | Làm cùng bộ file production khi có VPS (frontend build tĩnh + Nginx). |
| **S4** MediaMTX không xác thực publish | ⏳ | Cần đổi đồng thời `mediamtx.yml` và `LIVE_RTSP_URL` trên Jetson; làm khi triển khai VPS. |
| **S5** Backend tin `role` trong JWT | ⏳ (giới hạn đã biết) | Nên nêu trong mục "Hạn chế" của khóa luận, hoặc rút `JWT_EXPIRES_IN` xuống 1 ngày. |

### 2.5. ⚪ Thấp và tổ chức

| ID | Trạng thái | Chi tiết |
|---|---|---|
| **L1** Chưa có git | ✅ | `git init`, commit mốc `fdd2185`. Bổ sung `.gitignore` (bỏ thư mục `_backup_*`, cache runtime, `.pipeline.lock`). Thêm `.gitattributes` giữ **LF** cho `.sh`/`.py`/`.yml`, để script không lỗi khi copy sang Jetson. Thư mục `_backup_truoc_khi_sua_*` và `edge-ai-gan-full` **giữ nguyên trên đĩa**, chỉ không đưa vào git. |
| **L2** `_seen_track_ids` tăng mãi | ✅ | Chuyển thành dict `{track_id: thời điểm}`, dọn các mục cũ hơn 10 phút khi vượt 2.000 mục. |
| **L3** Entry rate dùng đồng hồ máy | ✅ | Dùng thời gian sự kiện của luồng video, cùng đồng hồ với tốc độ và mật độ. |
| **L4** Ghi đĩa mỗi telemetry | ⏳ | Ổn với quy mô vài node. Ghi vào phần "Hạn chế và hướng phát triển". |
| **L5** Không có test | ✅ | `tests/test_analytics.py` (21 test) và `tests/test_contracts.py` (7 test). |

---

## 3. Những thay đổi về hành vi cần biết

1. **`.env` bắt buộc có đủ khóa.** `EDGE_TOKEN` và `MQTT_PASS` (file `.env` gốc), `JWT_SECRET` (`webgis/auth-service/.env`). Hiện cả ba **đều đã có**, nên hệ thống chạy được ngay.
2. **Chỉ một `main.py` được chạy.** Chạy bản thứ hai sẽ thấy `Another pipeline instance is running…` và thoát với mã 3. Khi bấm Start trên WebGIS lúc đang có `main.py` chạy tay, agent sẽ **dừng bản chạy tay rồi tiếp quản**.
3. **Thuật toán v2 thận trọng hơn với ngoại lai.** Phân loại dùng **trung vị** thời gian lưu và thời gian dừng thay vì giá trị lớn nhất. Phần mô tả thuật toán trong khóa luận cần cập nhật theo:
   - "max dwell" → "median dwell", "thời gian dừng" = từ lúc dừng;
   - thang điểm FREE < 35 ≤ SLOW < 65 ≤ CONGESTED.
4. **Vùng loại trừ giờ có tác dụng thật.** Nếu file ROI có `exclusion_polygons`, số xe hiển thị sẽ **giảm** tương ứng (xem trường `excluded_vehicle_count`). File `configs/roi_traffic_nano.json` hiện **không** có vùng loại trừ, nên số liệu không đổi.
5. **Khách (USER/chưa đăng nhập)** vẫn xem được biểu đồ lịch sử nhưng **không** xem được ảnh snapshot.
6. **`configs/config_infer_yolo11_nano.txt`** sẽ được tự ghi đường dẫn tuyệt đối khi chạy trên Jetson. Hành vi tự sửa này đã có từ trước, nay dùng đúng thư mục gốc.
7. **Log mới ở phía Jetson viết bằng tiếng Anh không dấu**, để không lỗi `UnicodeEncodeError` khi service systemd chạy với locale C (Python 3.6).

---

## 4. Việc bạn cần làm

### 4.1. Đổi các khóa đã lộ (bắt buộc trước khi đưa lên internet)
1. **HiveMQ Cloud:** đổi mật khẩu user MQTT trên console, rồi cập nhật `MQTT_PASS` trong `.env` gốc trên **cả PC và Jetson**.
2. **`EDGE_TOKEN`:** tạo chuỗi ngẫu nhiên, đặt **giống nhau** ở `.env` gốc trên PC và trên Jetson. Lệnh tạo chuỗi:
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
3. **`JWT_SECRET`** trong `webgis/auth-service/.env`: đổi sang chuỗi ngẫu nhiên khác. Mọi người dùng sẽ phải đăng nhập lại một lần.

### 4.2. Cho phép agent restart `nvargus-daemon` không cần mật khẩu (tùy chọn)
Agent nay gọi `sudo -n`, nên sẽ báo lỗi ngay thay vì treo chờ nhập mật khẩu. Muốn agent tự giải phóng camera bị kẹt thì thêm quy tắc sudoers trên Jetson. Chạy `sudo visudo -f /etc/sudoers.d/nvargus` và thêm dòng sau (thay `<user>` bằng tài khoản chạy agent):
```
<user> ALL=(root) NOPASSWD: /bin/systemctl restart nvargus-daemon
```

### 4.3. Bật đồng bộ thời gian trên Jetson
```bash
sudo timedatectl set-ntp true
```

---

## 5. Danh sách kiểm tra trên Jetson Nano

Chép mã mới sang Jetson (giữ nguyên `.env` trên máy đó), rồi kiểm tra lần lượt:

| # | Kiểm tra | Cách làm | Kết quả mong đợi |
|---|---|---|---|
| 1 | Unit test trên Python 3.6 | `python3 -m unittest discover -s tests -v` | 28 test OK (test TTL có thể bị *skip* nếu thiếu paho, nhưng Jetson có sẵn) |
| 2 | Khóa một bản | Chạy `python3 main.py csi --no-mqtt` ở 2 terminal | Terminal 2 báo `Another pipeline instance…`, thoát mã 3; terminal 1 vẫn nhận diện bình thường |
| 3 | Agent không làm chết camera | Chạy `main.py csi` bằng tay và bật agent, rồi bấm "Chụp preview" trên WebGIS | Ảnh preview hiện ra; cửa sổ nhận diện **không** bị đứng; log agent có `pipeline is running, requesting frame…` |
| 4 | Preview khi pipeline chạy (H1) | Như bước 3 | File `.latest_preview.jpg` được tạo; log **không** có `Preview capture error` |
| 5 | Ảnh bằng chứng (C1) | Cho ROI ùn tắc ≥ 15 s (hoặc dùng video kẹt xe) | Thư mục `snapshot_outbox` trống dần; ảnh hiện trong "Lịch sử ùn tắc" trên WebGIS (đăng nhập Staff) |
| 6 | Start/Stop từ WebGIS | Start, rồi Stop, rồi Start lại | Không còn lỗi `Resource busy`; heartbeat hiển thị đúng trạng thái |
| 7 | FPS (M10, H3) | So FPS trong log `[TRAFFIC] fps=…` trước và sau khi sửa | FPS không giảm. Kỳ vọng tăng nhẹ khi chạy lâu > 15 phút. **Ghi số liệu này vào Bảng 2 của khóa luận.** |
| 8 | Docker (H5), nếu dùng | `docker compose up -d --build`, đăng nhập Staff, mở bảng điều khiển node | Các API Staff không trả 401 |

---

## 6. Phần còn lại cho khóa luận (không thuộc sửa mã)

1. **Số liệu thực nghiệm (P3):** 3 bảng trong `BAO_CAO_TIEN_DO_NGHIEN_CUU_EDGE_AI.md` (mAP, FPS/tài nguyên, MAE tốc độ) vẫn trống. Đây là ưu tiên số 1.
2. **Đánh giá v1/v2 trên dữ liệu thật:** công cụ `tools/compare_congestion_models.py` hiện dùng **kịch bản tổng hợp** và đưa số liệu thẳng vào bộ phân loại, nên kết quả **không đổi** trước và sau đợt sửa này (Accuracy v1 52,6 % / v2 54,8 %; Recall v2 chỉ 12,9 %). Con số này **chưa nên đưa vào khóa luận** làm kết luận. Cần quay video thật, gán nhãn tay theo từng khoảng thời gian, rồi chạy lại qua `TrafficAnalyzer` để có confusion matrix đáng tin.
3. **Triển khai VPS:** S3, S4 và bộ file production (Nginx, frontend build tĩnh, MediaMTX có xác thực) làm khi đã có máy chủ.
4. **Commit:** các thay đổi đang nằm ở working tree. Sau khi bạn xem lại (`git diff`) và chạy thử trên Jetson thì commit thành một mốc "Sửa lỗi theo báo cáo rà soát".
