# ĐỊNH HƯỚNG PHÁT TRIỂN TƯƠNG LAI (FUTURE WORK)
## HỆ THỐNG AI DỰ BÁO ÙN TẮC GIAO THÔNG TẬP TRUNG TẠI SERVER
> **Mã định danh vấn đề:** `D2 — Traffic Congestion Prediction & Forecasting`  
> **Trạng thái hiện tại:** Đã tạm tắt mô hình hồi quy tuyến tính cục bộ trên Edge để tối ưu hóa tài nguyên; chuyển toàn bộ kiến trúc dự báo dài hạn thành **Module Machine Learning/Deep Learning tập trung tại Backend WebGIS**.  
> **Mục tiêu:** Xây dựng hệ thống giao thông thông minh dự báo trước nguy cơ ùn tắc trong 15 — 60 phút tiếp theo dựa trên chuỗi thời gian lịch sử từ các trạm Edge AI.

---

## 1. BỐI CẢNH & NGUYÊN NHÂN CHUYỂN ĐỔI KIẾN TRÚC

### 1.1. Hạn chế của việc chạy Forecast trên Jetson Edge
Trong phiên bản thử nghiệm ban đầu, module `traffic_classifier.py` trên Edge đã tích hợp hàm hồi quy tuyến tính `_compute_forecast` dựa trên 300–900 giây lịch sử gần nhất và gửi kèm vào payload telemetry mỗi giây một lần. Tuy nhiên, qua quá trình đánh giá thực tế và audit hệ thống:
1. **Lãng phí tài nguyên tính toán & băng thông mạng:** Dòng trạng thái giao thông 5–10 phút không biến đổi theo từng giây. Việc tính toán ma trận hồi quy và gửi lặp lại mỗi giây làm tăng tải CPU và kích thước payload MQTT không cần thiết.
2. **Hạn chế tầm nhìn không gian (Spatial Blindness):** Một trạm camera Edge chỉ quan sát được một vùng quan sát hẹp (ROI 30–100m). Tuy nhiên, hiện tượng ùn tắc giao thông là kết quả của **sự tương quan chuỗi thời gian và không gian (Spatial-Temporal Correlation)**. Ví dụ: Ngã tư B bị ùn ứ vào lúc 17h30 thường là do lưu lượng phương tiện từ Ngã tư A cách đó 1km dồn về sau 10–15 phút di chuyển. Một camera đơn lẻ tại trạm B hoàn toàn "mù" trước thông tin này.
3. **Mô hình hồi quy tuyến tính không phản ánh được phi tuyến tính:** Dòng giao thông đô thị có tính chất bất đối xứng và chuyển pha đột ngột (từ lưu thông tự do sang nghẽn bão hòa). Hồi quy tuyến tính thô sơ thường dự báo sai lệch lớn khi có đèn đỏ hoặc dòng xe dừng đột ngột.

### 1.2. Quyết định kiến trúc chuẩn
* **Tại Edge (Jetson Nano / Orin Nano):** Tập trung 100% năng lực phần cứng cho các tác vụ thời gian thực then chốt: Thị giác máy tính YOLOv11 Nano, NvDCF Tracker, phân loại trạng thái tức thời đa tiêu chí (TCVN 4054:2005) và phát video trực tiếp. Tạm thời tắt gửi trường `forecast` chưa hoàn thiện.
* **Tại Trung tâm (FastAPI Backend & Cloud):** Tiếp nhận dữ liệu lưu lượng tổng hợp theo phút từ cơ sở dữ liệu `history.db` (đã xây dựng ở **D1**), kết hợp với thông tin không gian mạng lưới đường GIS để huấn luyện và suy luận các mô hình Machine Learning/Deep Learning chuyên sâu.

```
+-------------------------------------------------------------+
|                     TRẠM CAMERA EDGE AI                    |
|  [Camera CSI] -> [YOLOv11] -> [Tracker] -> [Đo V/Mật độ/LOS] |
+-------------------------------------------------------------+
                               |
                               | (MQTT Telemetry 1Hz)
                               v
+-------------------------------------------------------------+
|                   WEBGIS BACKEND & SERVER                   |
|                                                             |
|  [SQLite history.db (Bảng traffic_timeline theo phút)]      |
|                               |                             |
|                               v                             |
|               [AI Traffic Forecast Service]                 |
|             (Mô hình XGBoost / LSTM / LightGBM)             |
|                               |                             |
|                               v                             |
|    API: GET /api/v1/forecast/{segment_id}?horizon=15m       |
+-------------------------------------------------------------+
                               |
                               v
+-------------------------------------------------------------+
|                  WEBGIS FRONTEND DASHBOARD                  |
|  - Biểu đồ Lịch sử (đường liền nét)                          |
|  - Dự báo 15/30/60 phút tới (đường đứt nét + khoảng tin cậy)|
|  - Cảnh báo sớm nguy cơ ùn tắc diện rộng                    |
+-------------------------------------------------------------+
```

---

## 2. DỮ LIỆU HUẤN LUYỆN (DATASET & FEATURE ENGINEERING)

Nhờ cơ sở dữ liệu SQLite `traffic_timeline` đã được chuẩn hóa tại **D1**, dữ liệu huấn luyện đã sẵn sàng được tích lũy theo từng phút:

### 2.1. Cấu trúc trường dữ liệu thô (Raw Features)
| Tên trường | Kiểu dữ liệu | Ý nghĩa |
| :--- | :--- | :--- |
| `minute_ts` | TEXT (ISO) | Mốc thời gian tổng hợp (vd: `2026-10-29T10:15:00`) |
| `segment_id` | TEXT | Mã định danh đoạn đường / nút giao |
| `avg_speed_kmh` | REAL | Vận tốc trung bình trong phút (km/h) |
| `congestion_score`| INTEGER | Điểm số ùn tắc thực tế (0 — 100) |
| `vehicle_count` | INTEGER | Số lượng phương tiện trung bình trong phút |
| `pce_density` | REAL | Mật độ xe con quy đổi (PCU/km/làn theo TCVN 4054:2005) |
| `traffic_status` | TEXT | Nhãn trạng thái (`FREE`, `SLOW`, `CONGESTED`) |

### 2.2. Kỹ thuật sinh đặc trưng phái sinh (Feature Engineering)
Để mô hình AI học được quy luật giờ cao điểm, xu hướng và quán tính giao thông:
1. **Đặc trưng Lịch trình & Thời gian (Calendar Features):**
   * `hour_of_day`: Giờ trong ngày (0 — 23).
   * `minute_of_hour`: Phút trong giờ (0 — 59).
   * `day_of_week`: Thứ trong tuần (0: Thứ Hai — 6: Chủ Nhật).
   * `is_weekend`: Cờ ngày cuối tuần (0 hoặc 1).
   * `is_rush_hour`: Cờ giờ cao điểm (Sáng: 7h00–8h30, Chiều: 17h00–18h30).
   * `sin_hour`, `cos_hour`: Mã hóa chu kỳ 24h bằng hàm lượng giác (Cyclical encoding).
2. **Đặc trưng Độ trễ Quá khứ (Lag Features):**
   * `speed_lag_5m`, `speed_lag_10m`, `speed_lag_15m`, `speed_lag_30m`.
   * `score_lag_5m`, `score_lag_10m`, `score_lag_15m`, `score_lag_30m`.
   * `pce_density_lag_5m`, `pce_density_lag_15m`.
3. **Đặc trưng Biến thiên & Động lượng (Trend / Momentum Features):**
   * $\Delta_{\text{speed}} = V_t - V_{t-5}$: Độ sụt giảm vận tốc trong 5 phút.
   * $\text{SMA}_{15}(V)$: Trung bình trượt 15 phút.
   * Tỷ lệ gia tăng mật độ xe con theo phút.

---

## 3. CÁC MÔ HÌNH HỌC MÁY ĐỀ XUẤT

### Phương án 1: Gradient Boosted Decision Trees (XGBoost / LightGBM) — *Ưu tiên triển khai bước 1*
* **Bản chất:** Hồi quy đa mục tiêu dựa trên cây quyết định tăng cường.
* **Mục tiêu dự đoán:**
  * $\hat{Y}_{t+15}$: Dự đoán `congestion_score` và `avg_speed` sau 15 phút.
  * $\hat{Y}_{t+30}$: Dự đoán sau 30 phút.
* **Lý do lựa chọn:**
  * Tốc độ huấn luyện cực nhanh (dưới 1 phút trên CPU server thông thường).
  * Khả năng chống nhiễu (outliers) tốt hơn các mô hình tham số.
  * Hỗ trợ xuất biểu đồ **Feature Importance** (SHAP values): Giải thích minh bạch yếu tố nào đóng góp lớn nhất vào nguy cơ kẹt xe (ví dụ: giờ tan tầm chiếm 45%, sụt tốc độ 10 phút trước chiếm 30%).

### Phương án 2: Recurrent Neural Network (LSTM / GRU) — *Triển khai bước 2*
* **Bản chất:** Mạng nơ-ron hồi quy học sâu xử lý dữ liệu chuỗi thời gian tuần tự.
* **Kiến trúc mạng:**
  * Input: Vector kích thước $(B, T=30, F=12)$ — chuỗi 30 bước quá khứ, 12 đặc trưng.
  * 2 lớp Bi-directional LSTM (64 hidden units) + Dropout (0.2).
  * Dense output layer: Vector $(B, H=15)$ tương ứng với 15 bước dự báo tương lai.
* **Hàm mất mát:** Huber Loss hoặc MSE kết hợp MAE để phạt mạnh các điểm dự đoán trễ pha.

---

## 4. THIẾT KẾ GIAO DIỆN & API TRUNG TÂM

### 4.1. RESTful API Endpoint
```http
GET /api/v1/forecast/{segment_id}?horizon=30
```
**Response Schema (JSON):**
```json
{
  "segment_id": "segment-001",
  "generated_at": "2026-10-29T10:30:00+07:00",
  "model_version": "xgboost-v1.2",
  "confidence_score": 0.92,
  "current": {
    "traffic_status": "FREE",
    "congestion_score": 25,
    "avg_speed_kmh": 38.5
  },
  "predictions": [
    {
      "minutes_ahead": 15,
      "predicted_at": "2026-10-29T10:45:00+07:00",
      "predicted_status": "SLOW",
      "predicted_congestion_score": 58,
      "predicted_speed_kmh": 22.0,
      "confidence_lower": 50,
      "confidence_upper": 65
    },
    {
      "minutes_ahead": 30,
      "predicted_at": "2026-10-29T11:00:00+07:00",
      "predicted_status": "CONGESTED",
      "predicted_congestion_score": 82,
      "predicted_speed_kmh": 9.5,
      "confidence_lower": 74,
      "confidence_upper": 90
    }
  ]
}
```

### 4.2. Trực quan hóa trên WebGIS Dashboard
* Trong component `NodeDashboardDrawer`: Biểu đồ `HistoryTimeline` hiển thị 2 phần rõ rệt:
  * Trục thời gian từ quá khứ đến hiện tại: Biểu diễn bằng **đường vẽ liền nét** (Dữ liệu quan sát thực tế).
  * Trục thời gian từ hiện tại đến tương lai (15–30–60 phút): Biểu diễn bằng **đường vẽ nét đứt (Dashed line)** kèm vùng bóng mờ mờ biểu thị khoảng tin cậy $\pm 10\%$.
  * Huy hiệu trạng thái dự báo (Forecast Pill): *"Dự báo 15p: Có nguy cơ chuyển sang Chậm"* kèm màu cảnh báo cam/đỏ.

---

## 5. KẾ HOẠCH TRIỂN KHAI 4 GIAI ĐOẠN

| Giai đoạn | Nhiệm vụ chính | Sản phẩm đầu ra |
| :--- | :--- | :--- |
| **Giai đoạn 1** *(Hiện tại)* | Tắt tạm thời forecast thô trên Jetson Edge; tích lũy dữ liệu lịch sử qua SQLite `traffic_timeline` (D1). | Hệ thống vận hành mượt mà, không lãng phí băng thông; dataset tự động tích lũy. |
| **Giai đoạn 2** | Viết script xuất dữ liệu `tools/export_traffic_dataset.py` trích xuất CSV từ SQLite; tạo kịch bản mô phỏng giờ cao điểm bằng `simulate_edge.py`. | Dataset gồm hàng chục nghìn mẫu chuỗi thời gian sạch. |
| **Giai đoạn 3** | Xây dựng Jupyter Notebook huấn luyện thử nghiệm mô hình XGBoost và LSTM; tinh chỉnh siêu tham số và đánh giá qua MAE, RMSE, $R^2$. | File mô hình đã tối ưu hóa `traffic_forecast_model.pkl` hoặc `.onnx`. |
| **Giai đoạn 4** | Xây dựng Background Task trong FastAPI Backend tải model và chạy inference mỗi 5 phút; cập nhật Frontend hiển thị dự báo tương lai. | Tính năng AI Dự Báo Ùn Tắc hoàn chỉnh end-to-end trên WebGIS. |

---

## 6. KỊCH BẢN THUYẾT MINH & TRẢ LỜI HỘI ĐỒNG KHÓA LUẬN

Khi Thầy/Cô trong Hội đồng hỏi:
> **Câu hỏi:** *"Hệ thống của em hiện tại có tính năng dự đoán trước kẹt xe trong 15-30 phút tới không? Tại sao em không tích hợp luôn vào Jetson Nano?"*

**Cách trả lời ghi điểm tối đa:**
> *"Dạ thưa Thầy/Cô, đây chính là định hướng phát triển trọng tâm trong Chương 5 (Hướng phát triển tương lai) của đề tài em.*
>
> *1. **Về mặt kiến trúc phần cứng:** Thiết bị Edge (Jetson Nano) chỉ có tài nguyên GPU và VRAM hữu hạn, đã phải gánh tối đa mô hình thị giác máy tính YOLOv11 và Tracker thời gian thực. Hơn nữa, một camera cục bộ chỉ có góc nhìn hẹp vài chục mét, không thể tự mình dự báo được hiện tượng kẹt xe mang tính chất mạng lưới giao thông.*
>
> *2. **Về giải pháp đề xuất:** Nhờ cơ chế tổng hợp lưu lượng theo từng phút vào cơ sở dữ liệu tập trung ở Backend mà đề tài đã xây dựng (bảng `traffic_timeline`), hệ thống đang tích lũy dữ liệu chuỗi thời gian chuẩn xác gồm vận tốc, mật độ quy đổi xe con tiêu chuẩn theo TCVN 4054:2005 và tỷ lệ dừng bánh.*
>
> *3. **Hướng triển khai AI tiếp theo:** Em đã hoàn thiện thiết kế kỹ thuật để triển khai mô hình Machine Learning chuỗi thời gian (như XGBoost hoặc LSTM) đặt tập trung tại Server. Mô hình này nhận chuỗi 30 phút lịch sử kết hợp thông tin giờ cao điểm và ngày trong tuần để dự báo điểm số kẹt xe cho 15 đến 30 phút tiếp theo, sau đó trực quan hóa đường nét đứt dự báo trực tiếp trên bản đồ WebGIS."*

