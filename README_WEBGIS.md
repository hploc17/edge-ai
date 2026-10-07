# 🌐 HƯỚNG DẪN KHỞI ĐỘNG VÀ VẬN HÀNH WEBGIS OPERATIONS CENTER

Hệ thống Trung tâm Vận hành và Giám sát Giao thông Thông minh (**WebGIS Traffic Operations Center**), kết hợp giữa **FastAPI Backend Hub** và **React (MapLibre + TailwindCSS) Frontend**.

---

## 🚀 1. Khởi động nhanh (1-Click)

### Trên Windows
Có 2 phương thức khởi động:

1. **Chế độ Phát triển (Development Mode - Khuyên dùng khi code/sửa giao diện):**
   - Click đúp vào file [`start_webgis.bat`](start_webgis.bat) (hoặc [`start_webgis_dev.bat`](start_webgis_dev.bat)).
   - Hệ thống tự kiểm tra môi trường, tự cài thư viện nếu thiếu, và mở đồng thời 2 cửa sổ:
     - **Backend FastAPI Hub:** http://localhost:8000 (Tài liệu API Swagger: http://localhost:8000/docs)
     - **Frontend Vite React:** http://localhost:5173
   - Truy cập giao diện giám sát tại: **http://localhost:5173**

2. **Chế độ Hoàn chỉnh / Production (Single Port 8000):**
   - Click đúp vào file [`start_webgis_prod.bat`](start_webgis_prod.bat).
   - Hệ thống tự build Frontend và khởi động FastAPI phục vụ cả Web UI lẫn API trên cổng duy nhất: **http://localhost:8000**

### Trên Linux / Ubuntu / macOS
Chạy terminal:
```bash
chmod +x start_webgis.sh
./start_webgis.sh
```

---

## 🧪 2. Chạy Giả lập Dữ liệu Giao thông (Simulator)
Nếu bạn chưa có thiết bị Jetson Nano hoặc Camera ngoài thực địa, bạn có thể kích hoạt bộ giả lập để đẩy dữ liệu xe ảo, tọa độ GPS, mức độ ùn tắc và telemetry lên MQTT Broker:

- **Windows:** Click đúp file [`simulate_traffic.bat`](simulate_traffic.bat)
- **Hoặc Terminal:**
  ```bash
  python webgis/tools/simulate_edge.py
  ```
Sau khi bật, bản đồ WebGIS sẽ hiển thị ngay vị trí camera `edge-01`, lưu lượng xe và các thông số telemetry thời gian thực.

---

## 🛠️ 3. Khởi động thủ công bằng dòng lệnh

### Backend (FastAPI Hub)
```bash
cd webgis/backend
pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### Frontend (React + Vite)
```bash
cd webgis/frontend
npm install
npm run dev
```

---

## 📋 4. Yêu cầu môi trường
- **Python:** >= 3.10
- **Node.js:** >= 18.0 (kèm npm)
- **MQTT Broker:** Mặc định cấu hình HiveMQ Cloud (đã tích hợp sẵn thông tin kết nối trong `backend/config.py`).
