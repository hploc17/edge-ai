# MediaMTX - Trạm Trung Chuyển Video Live Stream cho WebGIS

## 1. Giới thiệu
MediaMTX (trước đây là rtsp-simple-server) là media server chuyên dụng mã nguồn mở hiệu năng cao viết bằng Go.
Hệ thống sử dụng MediaMTX để:
1. Nhận luồng video H.264 từ camera CSI Jetson Nano đẩy lên qua giao thức RTSP (`rtspclientsink`).
2. Chuyển đổi theo thời gian thực (Zero transcoding overhead) sang:
   - **WebRTC (WHEP):** Độ trễ siêu thấp (< 500ms) hiển thị trực tiếp trên trình duyệt WebGIS.
   - **LL-HLS (Low-Latency HLS):** Độ trễ 1-2s làm phương án dự phòng khi mạng client bị chặn UDP.

---

## 2. Các cổng mạng (Ports) cần mở
- **8554 (TCP/UDP):** RTSP Ingest từ Jetson Nano.
- **8888 (TCP):** HLS HTTP server (phục vụ `index.m3u8` và các fMP4 chunks).
- **8889 (TCP):** WebRTC HTTP signaling / WHEP endpoint.
- **8189 (UDP):** WebRTC ICE UDP data traffic.

---

## 3. Cách khởi chạy

### Cách A: Chạy bằng Docker (Khuyên dùng trên Linux / Server)
```bash
cd deploy/mediamtx
docker compose up -d
```

### Cách B: Chạy Binary trực tiếp (Dành cho Windows PC phát triển)
1. Tải bản MediaMTX dành cho Windows (64-bit) từ GitHub:
   `https://github.com/bluenviron/mediamtx/releases`
2. Giải nén file `mediamtx.exe` vào thư mục này (`deploy/mediamtx/`).
3. Chạy lệnh:
   ```cmd
   mediamtx.exe mediamtx.yml
   ```
Server sẽ tự động lắng nghe trên các cổng 8554, 8888, 8889.

---

## 4. Kiểm tra luồng phát
Khi Jetson Nano đẩy luồng lên địa chỉ:
`rtsp://<MEDIAMTX_HOST>:8554/live/edge-01`

Bạn có thể xem ngay trên trình duyệt:
- **Trang WebRTC kiểm tra:** `http://<MEDIAMTX_HOST>:8889/live/edge-01`
- **Luồng HLS:** `http://<MEDIAMTX_HOST>:8888/live/edge-01/index.m3u8`
- **VLC Media Player:** Mở Network Stream `rtsp://<MEDIAMTX_HOST>:8554/live/edge-01`
