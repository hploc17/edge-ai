# HƯỚNG DẪN ĐO ĐẠC HIỆU NĂNG VÀ ĐỘ TRỄ LIVE STREAM (AIoT THESIS BENCHMARK)

Tài liệu này cung cấp quy trình chuẩn để đo đạc và báo cáo hiệu năng hệ thống giám sát giao thông trên **Nvidia Jetson Nano 4GB** kết hợp **MediaMTX** và **WebGIS**.

---

## 1. Phương pháp đo độ trễ đầu-cuối (Glass-to-Glass Latency)

Độ trễ "Glass-to-Glass" là khoảng thời gian từ khi ánh sáng đi vào thấu kính camera CSI cho đến khi photon hiển thị trên màn hình người dùng qua WebGIS.

### Quy trình thực hiện:
1. Mở đồng hồ bấm giờ hiển thị mili-giây (ví dụ: truy cập [online-stopwatch.com](https://www.online-stopwatch.com) trên điện thoại hoặc máy tính bảng).
2. Hướng **Camera CSI của Jetson** quay trực diện vào màn hình đồng hồ đó.
3. Trên máy tính giám sát, mở giao diện **WebGIS**, click vào nút giao hoặc mở camera popup xem luồng trực tiếp (WebRTC hoặc LL-HLS).
4. Đặt điện thoại (hoặc đồng hồ nguồn) cạnh màn hình hiển thị WebGIS.
5. Dùng một máy ảnh / điện thoại khác chụp một bức ảnh chụp đồng thời cả 2 màn hình:
   - **T_nguon**: Thời gian hiển thị trên đồng hồ gốc.
   - **T_web**: Thời gian hiển thị trên luồng video WebGIS.
6. **Công thức tính độ trễ:**
   $$\Delta T = T_{\text{nguon}} - T_{\text{web}}$$

### Giá trị kỳ vọng:
- **WebRTC WHEP (UDP/TCP):** `200ms - 450ms` (Siêu trễ thấp, phản xạ thời gian thực).
- **LL-HLS (HTTP):** `1500ms - 2500ms` (Dự phòng qua firewall / mạng công ty chặn UDP).

---

## 2. Đo đạc tải phần cứng Jetson Nano (`tegrastats`)

Trên Jetson Nano, tiện ích `tegrastats` cung cấp thông số thời gian thực về CPU, GPU, RAM, EMC (băng thông bộ nhớ), nhiệt độ và công suất tiêu thụ điện.

### Khởi động ghi log tài nguyên:
Mở terminal trên Jetson (hoặc SSH vào Jetson):
```bash
sudo tegrastats --interval 1000 | tee tegrastats_benchmark.log
```

### Cách đọc các trường dữ liệu quan trọng:
- **`RAM xxxx/3964MB`**: Dung lượng RAM hệ thống đang sử dụng (Jetson dùng chung unified memory cho CPU và GPU).
- **`CPU [x%@1479, y%@1479, z%@1479, w%@1479]`**: Tỉ lệ phần trăm tải của 4 lõi ARM Cortex-A57.
- **`GR3D_FREQ x%`**: Tỉ lệ hoạt động của GPU Maxwell 128-core (nơi DeepStream chạy YOLO và NVDSOSD).
- **`NVENC`**: Bộ mã hóa phần cứng H.264 (`nvv4l2h264enc`). Khi Live Stream bật, NVENC hoạt động mà hoàn toàn không ăn tải CPU.
- **`EMC_FREQ x%`**: Bộ điều khiển bộ nhớ (Memory Controller bus load).
- **`POM_5V_IN xxxx/xxxx`**: Công suất tiêu thụ điện tức thời (mW).

---

## 3. Kịch bản đánh giá so sánh (A/B Testing)

Để chứng minh tính ưu việt của thiết kế **On-Demand GStreamer Valve & Hardware Encoding**, tiến hành đo đạc 2 trạng thái:

### Trạng thái A: Chỉ chạy AI ngầm (Live Stream TẮT - Van valve đóng)
1. Đảm bảo không có trình duyệt nào đang mở popup xem camera.
2. GStreamer pipeline DeepStream vẫn chạy phân tích YOLO, theo dõi phương tiện và gửi MQTT telemetry.
3. Ghi nhận `tegrastats` liên tục trong 120 giây.

### Trạng thái B: Vừa chạy AI vừa Live Stream (Live Stream BẬT - Van valve mở)
1. Mở WebGIS, bấm xem camera để gửi lệnh MQTT `start_live`.
2. Van GStreamer mở ra, nvv4l2h264enc bắt đầu nén H.264 và đẩy lên MediaMTX qua RTSP.
3. Người dùng xem luồng WebRTC trên WebGIS.
4. Ghi nhận `tegrastats` liên tục trong 120 giây.

---

## 4. Bảng biểu số liệu mẫu cho Báo cáo Đồ án

| Chỉ số đánh giá | Trạng thái A (Chỉ chạy AI ngầm) | Trạng thái B (AI + Live WebRTC) | Chênh lệch (Impact) | Đánh giá kiến trúc |
| :--- | :---: | :---: | :---: | :--- |
| **Tải CPU trung bình (4 Cores)** | ~ 28 - 35% | ~ 30 - 38% | + 2 - 3% | Rất thấp (Do mã hóa H.264 chạy trên chip NVENC chuyên dụng) |
| **Tải GPU Maxwell (GR3D)** | ~ 75 - 85% | ~ 76 - 86% | + 1% | Pipeline xử lý khung AI chia sẻ từ OSD, không tốn thêm infer |
| **FPS Xử lý DeepStream** | ~ 15.0 fps | ~ 15.0 fps | 0 fps | Không làm sụt giảm tốc độ suy luận của mô hình |
| **Dung lượng VRAM/RAM** | ~ 2.1 GB | ~ 2.2 GB | + 100 MB | Bộ đệm queue và rtspclientsink chiếm dung lượng không đáng kể |
| **Băng thông mạng tải lên (Jetson)** | ~ 20 Kbps (MQTT) | ~ 1.5 Mbps (H.264) | + 1.5 Mbps | Kiểm soát tốt theo cấu hình `LIVE_BITRATE=1500000` |
| **Độ trễ đầu cuối (Latency)** | N/A | ~ 320 ms | 320 ms | Đạt chuẩn phản xạ thời gian thực trên WebGIS |
| **Công suất tiêu thụ (Power)** | ~ 7.2 W | ~ 8.1 W | + 0.9 W | Hoạt động an toàn trong ngưỡng nguồn 5V/4A của Jetson |

---

## 5. Phân tích kết luận kỹ thuật
1. **Kiến trúc Zero-Copy & Hardware Branching:** Việc sử dụng plugin `valve` và `nvv4l2h264enc` ngay sau `nvdsosd` cho phép tái sử dụng frame đã vẽ bounding box mà không cần CPU chuyển đổi mảng numpy hay nén JPEG bằng OpenCV.
2. **Cơ chế On-Demand bảo vệ Jetson:** Khi không có người xem trên WebGIS, van đóng hoàn toàn, không tiêu hao băng thông upload của mạng di động 4G tại nút giao và giảm thiểu sinh nhiệt cho Jetson Nano.
