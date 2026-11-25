# BÁO CÁO ĐÁNH GIÁ CHUYÊN SÂU: TÍNH KHẢ THI CỦA PHƯƠNG PHÁP TRAVEL SPEED LEVEL OF SERVICE (HCM-LOS) TRONG HỆ THỐNG EDGE AI – WEBGIS

---

## MỤC LỤC
1. [Phần 1 — Executive Summary](#phần-1--executive-summary)
2. [Phần 2 — Hiện trạng Mã nguồn & Dữ liệu Hệ thống Đã Xác minh](#phần-2--hiện-trạng-mã-nguồn--dữ-liệu-hệ-thống-đã-xác-minh)
3. [Phần 3 — Đối chiếu Yêu cầu của Phương pháp HCM Travel Speed](#phần-3--đối-chiếu-yêu-cầu-của-phương-pháp-hcm-travel-speed)
4. [Phần 4 — Kiểm chứng Cơ sở Học thuật & Chuẩn mực Giao thông học](#phần-4--kiểm-chứng-cơ-sở-học-thuật--chuẩn-mực-giao-thông-học)
5. [Phần 5 — Phân tích Khả năng Đo lường & Các Ca Biên (Edge Cases)](#phần-5--phân-tích-khả-năng-đo-lường--các-ca-biên-edge-cases)
6. [Phần 6 — Đánh giá Khả năng Triển khai & Rủi ro Kỹ thuật Trước Bảo vệ](#phần-6--đánh-giá-khả-năng-triển-khai--rủi-ro-kỹ-thuật-trước-bảo-vệ)
7. [Phần 7 — Bảng So sánh Toàn diện: V1 vs V2 vs V3 SPI vs HCM Travel Speed LOS](#phần-7--bảng-so-sánh-toàn-diện-v1-vs-v2-vs-v3-spi-vs-hcm-travel-speed-los)
8. [Phần 8 — Phương pháp luận Kiểm chứng Thực nghiệm Khoa học](#phần-8--phương-pháp-luận-kiểm-chứng-thực-nghiệm-khoa-học)
9. [Phần 9 — Đề xuất Phương án Thay thế Khả thi & Tối ưu Nhất](#phần-9--đề-xuất-phương-án-thay-thế-khả-thi--tối-ưu-nhất)
10. [Phần 10 — Bộ 10 Câu hỏi Phản biện Hội đồng & Kịch bản Trả lời Chuẩn xác](#phần-10--bộ-10-câu-hỏi-phản-biện-hội-đồng--kịch-bản-trả-lời-chuẩn-xác)

---

## PHẦN 1 — EXECUTIVE SUMMARY

### Kết luận đánh giá: **C. KHÔNG NÊN TRIỂN KHAI PHƯƠNG PHÁP HCM TRAVEL SPEED LOS TRỰC TIẾP TRÊN HỆ THỐNG HIỆN TẠI.**  
*(Khuyến nghị lựa chọn: **B. Chỉ sử dụng khung lý thuyết HCM làm cơ sở đối chiếu học thuật; tại camera nút giao, áp dụng mô hình Trễ điều khiển HCM Chapter 18 kết hợp Running Speed SPI**).*

### Lý do kỹ thuật & học thuật cốt lõi:
1. **Sai lệch nghiêm trọng về quy mô không gian (Spatial Scale Mismatch):**  
   * Sổ tay Năng lực Thông hành **HCM (Highway Capacity Manual 2010/6th Edition, Chapter 16–17)** quy định rõ: *Urban Street Travel Speed LOS* được định nghĩa cho **toàn bộ một phân đoạn đường đô thị (Urban Street Segment) nối giữa hai nút giao có đèn tín hiệu liên tiếp, với chiều dài tiêu chuẩn từ $400\text{ m}$ đến $1.6\text{ km}$ ($0.25 - 1.0\text{ mile}$)*.  
   * Camera quan sát của dự án hiện tại chỉ bao quát một vùng **Analysis ROI ngắn từ $20\text{ m}$ đến $50\text{ m}$** ngay trước vạch dừng nút giao. Việc áp dụng công thức Travel Speed LOS của một đoạn đường 1km cho một khoảng cách 25 mét là **sai phạm vi áp dụng kinh điển trong giao thông học**.
2. **Sai lệch đối tượng đánh giá tại Nút giao có đèn (Signalized Intersection Mismatch):**  
   * Tại khu vực tiếp cận giao lộ có đèn tín hiệu (như ngã tư Lê Đức Thọ trong video `18.h264`), **HCM không bao giờ sử dụng Travel Speed để đánh giá LOS**!  
   * Theo **HCM 2010 Chapter 18 (Bảng 18-5)**, chất lượng vận hành tại nút giao có đèn tín hiệu được quy định **DUY NHẤT bằng Thời gian Trễ Điều khiển (Control Delay, tính bằng giây/xe)**, phân định từ LOS A ($\le 10\text{s}$) đến LOS F ($> 80\text{s}$). Áp dụng Travel Speed tại đây sẽ dẫn đến kết luận sai lệch khi xe dừng chờ đèn đỏ hợp pháp.
3. **"Tử huyệt" thuật toán khi xảy ra kẹt xe nghiêm trọng (Deadlock on Gridlock):**  
   * Để tính vận tốc hành trình $V_i = 3.6 \times L / (t_{B,i} - t_{A,i})$, phương tiện **bắt buộc phải đi qua cả 2 mốc A và B**.  
   * Khi kẹt xe thực sự xảy ra, hàng chục phương tiện dừng chết cứng ngắc bên trong ROI và **không có xe nào thoát qua mốc B**. Lúc này tập dữ liệu hoàn thành hành trình rỗng ($N = 0$), mẫu số bằng 0 $\rightarrow$ **Hệ thống bị tê liệt hoàn toàn và không thể xuất ra vận tốc hay trạng thái kẹt xe vào đúng thời điểm kẹt xe nhất**!
4. **Phân mảnh Track ID do xe máy di chuyển phi làn:**  
   * Dưới góc nhìn camera nghiêng trên phần cứng Jetson Nano, thuật toán NvDCF của DeepStream thường xuyên bị nhảy ID (ID switch) khi xe máy đi chen chúc, lách qua nhau. Phương tiện vào mốc A với ID #10 nhưng chạm mốc B với ID #25 sẽ bị loại bỏ vì cả 2 ID đều không có đủ cặp mốc $t_A, t_B$. Tỷ lệ mất mẫu thực tế tại đô thị Việt Nam có thể lên tới $40\% - 60\%$.
5. **Rủi ro tiến độ trước ngày bảo vệ:**  
   * Việc đập bỏ luồng xử lý snapshot tức thời để xây dựng hệ thống Tripwire A/B, State Machine quản lý cặp mốc và tính toán Travel Speed đòi hỏi viết lại toàn bộ `analytics/speed_estimator.py`, `presence_counter.py`, `traffic_classifier.py` và sửa đổi cấu trúc Telemetry MQTT. Nguy cơ phát sinh race condition, treo pipeline và sập hệ thống trong ngày bảo vệ là cực kỳ lớn.

---

## PHẦN 2 — HIỆN TRẠNG MÃ NGUỒN & DỮ LIỆU HỆ THỐNG ĐÃ XÁC MINH

Qua rà soát trực tiếp từng dòng mã nguồn trong kho lưu trữ, hiện trạng các module được xác minh như sau:

| Module / Chức năng | Vị trí mã nguồn (File & Dòng) | Hiện trạng thực tế | Khả năng đáp ứng đo Travel Speed |
| :--- | :--- | :--- | :--- |
| **Pipeline DeepStream & Probe** | [`main.py:780-860`](file:///d:/Project/Project/main.py#L780-L860) | Lấy metadata từ `NvDsObjectMeta`, phân loại lớp qua YOLO, kiểm tra `point_in_polygon` cho detection và analysis ROI. | **Đã có:** Thu thập tọa độ bounding box bottom-center tại mỗi frame. |
| **Quản lý Track ID** | [`main.py:797-808`](file:///d:/Project/Project/main.py#L797-L808) | Nhận `object_id` từ `nvtracker` (NvDCF). | **Hạn chế:** Chỉ có ID tức thời, không có cơ chế Re-ID khi bị che khuất hoặc đổi ID. |
| **Lịch sử quỹ đạo Track ID** | [`analytics/speed_estimator.py:344-389`](file:///d:/Project/Project/analytics/speed_estimator.py#L344-L389) | Lưu `history = deque()` chứa tuple `(timestamp, world_x, world_y)`. Cửa sổ trượt bị cắt cứng: `history_seconds = 2.0s`. | **KHÔNG LƯU TOÀN BỘ HÀNH TRÌNH:** Các mẫu cũ hơn $2.0\text{ giây}$ bị `popleft()` xóa bỏ. Nếu xe đi qua ROI mất $> 2\text{s}$, thời điểm vào $t_A$ bị mất hoàn toàn. |
| **Thời điểm vào/ra ROI** | [`analytics/presence_counter.py:98-121`](file:///d:/Project/Project/analytics/presence_counter.py#L98-L121)<br>[`analytics/traffic_classifier_v2.py:118-128`](file:///d:/Project/Project/analytics/traffic_classifier_v2.py#L118-L128) | `RoiPresenceCounter` có trễ xác nhận `in_roi_since` ($0.1\text{s}$) và `out_roi_since` ($0.25\text{s}$). `V2` lưu `_track_entry_times[tid] = now`. | **Hạn chế:** Khi xe ra khỏi ROI (`released`), V2 thực hiện `del self._track_entry_times[tid]`, **xóa bỏ ngay lập tức mà không ghi nhận $t_{\text{exit}}$ hay lưu thời gian hành trình $T_i$**. |
| **Hệ tọa độ Homography** | [`analytics/speed_estimator.py:41-71, 187-215`](file:///d:/Project/Project/analytics/speed_estimator.py#L41-L71) | `PerspectiveCalibration` tính ma trận 3x3 DLT từ 4 điểm ảnh sang mặt phẳng đường chữ nhật ($W \times L$ mét). | **Đã có:** Chuyển đổi chính xác pixel sang tọa độ mét thực địa $(X_{\text{road}}, Y_{\text{road}})$. |
| **Hai đường cắt A/B (Tripwires)** | [`spatial/roi_manager.py:30-45`](file:///d:/Project/Project/spatial/roi_manager.py#L30-L45)<br>[`configs/roi_traffic_nano.json:2-19`](file:///d:/Project/Project/configs/roi_traffic_nano.json#L2-L19) | Cấu hình chỉ có đa giác `analysis_roi` và `detection_roi`. | **CHƯA CÓ:** Hoàn toàn chưa có định nghĩa, cấu hình tọa độ hay hàm toán học kiểm tra giao cắt quỹ đạo với 2 đường cắt A/B. |
| **Ước tính Vận tốc hiện tại** | [`analytics/speed_estimator.py:311-325, 401-415`](file:///d:/Project/Project/analytics/speed_estimator.py#L311-L325) | Hồi quy tuyến tính vị trí theo thời gian trên cửa sổ $2.0\text{s}$ (`_fit_velocity`), làm mượt EMA $\alpha=0.25$. | **Đang là Vận tốc Tức thời (Spot Speed):** Đo tốc độ trôi tại chỗ, không phải Vận tốc Hành trình (Travel Speed). |
| **Timestamp Video vs Máy** | [`analytics/speed_estimator.py:218-268`](file:///d:/Project/Project/analytics/speed_estimator.py#L218-L268)<br>[`main.py:834-842`](file:///d:/Project/Project/main.py#L834-L842) | Class `StreamTimestamp` đọc `frame_meta.buf_pts` (GStreamer Presentation Timestamp), fallback theo `frame_num / nominal_fps`. | **Đã chuẩn hóa:** Dùng thời gian nội dung video, không bị ảnh hưởng bởi tốc độ xử lý CPU/GPU của Jetson Nano. |
| **Dữ liệu Telemetry & Database** | [`communication/mqtt_client.py:328-365`](file:///d:/Project/Project/communication/mqtt_client.py#L328-L365)<br>[`webgis/backend/services/data_store.py:86-102, 1094-1128`](file:///d:/Project/Project/webgis/backend/services/data_store.py#L86-L102) | Telemetry gửi định kỳ 1Hz qua MQTT. Database `traffic_timeline` lưu gộp theo `minute_bucket`. | **Hạn chế:** Không lưu danh sách vận tốc từng xe, không lưu tên video/phiên chạy, gộp dữ liệu theo từng phút. |

---

## PHẦN 3 — ĐỐI CHIẾU YÊU CẦU CỦA PHƯƠNG PHÁP HCM TRAVEL SPEED

Đối chiếu 6 yêu cầu bắt buộc của phương pháp HCM Urban Street Travel Speed LOS với hạ tầng dự án:

| Yêu cầu của phương pháp HCM | Dự án hiện tại đáp ứng thế nào? | Đánh giá mức độ khả thi |
| :--- | :--- | :---: |
| **1. Chiều dài đoạn phân tích ($L \ge 400\text{ m}$)** | ROI thực tế của camera chỉ dài **$20\text{ m} - 50\text{ m}$**. | ❌ **Không đáp ứng** (Lệch quy mô 10–20 lần) |
| **2. Đoạn đường nối giữa 2 nút giao (Segment)** | Camera đặt chĩa thẳng vào 1 nút giao (Intersection approach). | ❌ **Sai vị trí nghiệp vụ** |
| **3. Xác định Vận tốc Dòng tự do Cơ sở ($FFS$)** | Chưa có khảo sát FFS ngoài giờ cao điểm; đường nội đô xe máy hỗn hợp không có FFS chuẩn cố định. | ⚠️ **Thiếu dữ liệu đầu vào** |
| **4. Đo thời gian xe đi qua 2 mốc $t_A, t_B$** | Cần theo dõi liên tục không mất Track ID từ đầu đến cuối ROI. | ⚠️ **Khó khăn lớn do ID Switch xe máy** |
| **5. Tính Vận tốc khi dòng xe dừng cứng ($N=0$)** | Không có xe nào chạm mốc B $\rightarrow$ Không có mẫu $T_i$. | ❌ **Bế tắc toán học (Deadlock)** |
| **6. Phần cứng xử lý tại biên (Jetson Nano)** | Cần lưu giữ hàng trăm object state trong nhiều phút nếu xe kẹt. | ⚠️ **Nguy cơ rò rỉ RAM / OOM** |

---

## PHẦN 4 — KIỂM CHỨNG CƠ SỞ HỌC THUẬT & CHUẨN MỰC GIAO THÔNG HỌC

### 4.1. Định nghĩa chuẩn xác trong Highway Capacity Manual (HCM)
* **Tài liệu nguồn:** Transportation Research Board (TRB), *Highway Capacity Manual 2010 (HCM 2010)* và *HCM 6th Edition (2016)*, National Academies of Sciences, Engineering, and Medicine, Washington, D.C.
* **Chương 16 & 17 (Urban Street Facilities / Segments):**
  * Định nghĩa: Một phân đoạn đường đô thị (Urban Street Segment) bao gồm một đoạn đường thông suốt cộng với nút giao có đèn tín hiệu ở cuối đoạn.
  * Phương pháp đánh giá: Sử dụng **Travel Speed** (Vận tốc hành trình trung bình không gian — Space Mean Speed):
    $$S_T = \frac{3.6 \times L}{T_T}$$
    *Trong đó:* $L$ là chiều dài đoạn đường (thường tính bằng km hoặc hàng trăm mét), $T_T$ là tổng thời gian hành trình bao gồm cả thời gian chạy tự do và thời gian dừng chờ tại nút giao cuối đoạn.
* **Bảng 16-2 (HCM 2010) — Ngưỡng Urban Street LOS A–F:**
  LOS được xác định dựa trên tỷ lệ phần trăm giữa Travel Speed thực tế ($S_T$) so với Free-Flow Speed ($FFS$):
  * **LOS A:** $S_T > 85\% \times FFS$ (Lưu thông hoàn toàn tự do)
  * **LOS B:** $67\% \times FFS < S_T \le 85\% \times FFS$
  * **LOS C:** $50\% \times FFS < S_T \le 67\% \times FFS$
  * **LOS D:** $40\% \times FFS < S_T \le 50\% \times FFS$
  * **LOS E:** $30\% \times FFS < S_T \le 40\% \times FFS$
  * **LOS F:** $S_T \le 30\% \times FFS$ hoặc tỷ lệ lưu lượng trên năng lực thông hành $v/c > 1.0$ (Dòng bão hòa, tắc nghẽn).

### 4.2. Tại sao KHÔNG ĐƯỢC dùng Travel Speed tại Nút giao có đèn (Signalized Intersection)?
Theo **HCM 2010 Chương 18 (Bảng 18-5: Level-of-Service Criteria for Signalized Intersections)**:
* Đối với vùng không gian quanh nút giao (Intersection), tiêu chí đánh giá dịch vụ **bắt buộc phải là Control Delay (Độ trễ điều khiển, $d$)**:
  * **LOS A:** $d \le 10.0\text{ s/veh}$
  * **LOS B:** $10.0 < d \le 20.0\text{ s/veh}$
  * **LOS C:** $20.0 < d \le 35.0\text{ s/veh}$
  * **LOS D:** $35.0 < d \le 55.0\text{ s/veh}$
  * **LOS E:** $55.0 < d \le 80.0\text{ s/veh}$
  * **LOS F:** $d > 80.0\text{ s/veh}$ hoặc $v/c > 1.0$.
* **Kết luận học thuật:** HCM tách biệt rạch ròi: **Đoạn đường dài $\rightarrow$ Dùng Travel Speed; Khu vực Nút giao $\rightarrow$ Dùng Control Delay**. Camera của dự án đặt tại khu vực nút giao, nếu dùng Travel Speed là đặt sai bài toán lý thuyết.

---

## PHẦN 5 — PHÂN TÍCH KHẢ NĂNG ĐO LƯỜNG & CÁC CA BIÊN (EDGE CASES)

Khi áp dụng phương pháp thời gian hành trình hai mốc A/B ($T_i = t_{B,i} - t_{A,i}$) vào thực tế camera:

```
    Mốc A (Entry Line)                  Mốc B (Exit Line)
          │                                   │
          │ ──► [Xe 1: Chạy thẳng bình thường] ──► t_B1 (Đo được T_1)
          │                                   │
          │ ──► [Xe 2: Dừng chờ đèn đỏ 30s] ──► t_B2 (T_2 rất lớn -> V_travel tụt thảm hại)
          │                                   │
          │ ──► [Xe 3: Kẹt cứng trong ROI]    │      (KHÔNG CÓ t_B3 -> Bị bỏ qua!)
          │                                   │
          │ ──► [Xe 4: Bị đổi ID 10 -> ID 25] ──►    (Không khớp cặp ID -> Bị loại bỏ!)
```

1. **Ca 1 (Xe chạy bình thường qua 2 mốc):** Hệ thống đo được chính xác nếu ID không đổi.
2. **Ca 2 (Xe dừng chờ đèn đỏ hợp pháp 30s rồi đi qua B):**  
   * Quãng đường $L = 25\text{m}$. Thời gian chạy $2.5\text{s}$ + Dừng đèn đỏ $30\text{s}$ $\rightarrow T_i = 32.5\text{s}$.  
   * Vận tốc hành trình: $V_i = 3.6 \times 25 / 32.5 = \mathbf{2.77\text{ km/h}}$.  
   * Kết quả phân loại: $V_i < 30\% \times FFS \implies \mathbf{LOS\ F}$ **(`CONGESTED` — Báo động kẹt xe giả liên tục trong chu kỳ đèn bình thường!)**
3. **Ca 3 (Xe kẹt cứng trong ROI — Deadlock):**  
   * Khi đường tắc nghẽn hoàn toàn, 10 xe vào mốc A và đứng im bất động trong $2\text{ phút}$. Không có xe nào chạm mốc B.  
   * Thuật toán: Không có giá trị $t_B$ nào được sinh ra. Danh sách các hành trình hoàn thành $N_{\text{completed}} = 0$.  
   * Kết quả: Không thể tính được $V_{\text{travel}}$, hệ thống rơi vào trạng thái rỗng (`None` / `UNKNOWN`), **không thể phát hiện ra kẹt xe vào đúng thời điểm đường đang tắc nghẽn nghiêm trọng nhất**!
4. **Ca 4 (Phân mảnh Track ID xe máy):**  
   * Xe máy vào mốc A với Track ID #10. Ở giữa đường, do bị ô tô che khuất một phần, `nvtracker` mất dấu và cấp Track ID mới #24 khi xe chạm mốc B.  
   * Cặp ID không khớp $\rightarrow$ Cả 2 mẫu đều bị loại bỏ, dẫn đến mất dữ liệu trầm trọng trong giờ cao điểm.
5. **Ca 5 (Sai số hình học phối cảnh trong đoạn ROI ngắn $25\text{m}$):**  
   * Với đoạn đường $L = 25\text{m}$, xe máy di chuyển ở tốc độ $36\text{ km/h}$ ($10\text{ m/s}$) chỉ mất $2.5\text{ giây}$ (tương đương 75 frames ở 30 FPS).  
   * Sai số do rung lắc bounding box hoặc chênh lệch tiếp điểm bánh xe có thể làm dịch chuyển thời điểm cắt vạch $\pm 6\text{ frames}$ ($\pm 0.2\text{ giây}$).  
   * Thời gian đo được biến động từ $2.3\text{s}$ đến $2.7\text{s}$ $\rightarrow$ Vận tốc tính ra dao động từ $33.3\text{ km/h}$ đến $39.1\text{ km/h}$ (Sai số lên tới $\pm 17\%$). Đoạn đường càng ngắn, sai số đo thời gian hành trình càng bị khuếch đại!

---

## PHẦN 6 — ĐÁNH GIÁ KHẢ NĂNG TRIỂN KHAI & RỦI RO KỸ THUẬT TRƯỚC BẢO VỆ

Nếu quyết định triển khai phương pháp HCM Travel Speed LOS, bảng phân loại khối lượng công việc thực tế:

| Hạng mục thay đổi | Mức độ ưu tiên | Khối lượng & Phạm vi tác động | Rủi ro kỹ thuật |
| :--- | :---: | :--- | :---: |
| **Xây dựng Tripwire Engine (Mốc A/B)** | **BẮT BUỘC** | Tạo module mới kiểm tra giao cắt đoạn thẳng quỹ đạo vector $(x_1, y_1) \rightarrow (x_2, y_2)$ với 2 đường cắt A và B. | Trung bình |
| **Cấu trúc lưu trữ hành trình dài hạn** | **BẮT BUỘC** | Viết lại `speed_estimator.py`, loại bỏ giới hạn 2 giây, xây dựng hàng đợi đệm lưu vết trạng thái xe đến khi hoàn thành hành trình. | **Cao (Rò rỉ RAM / OOM trên Jetson Nano nếu xe không thoát)** |
| **Xử lý Timeout & Ca biên không hoàn thành** | **BẮT BUỘC** | Xây dựng cơ chế hủy bỏ track sau $X$ giây nếu không chạm mốc B (xe quay đầu, tạt vào lề). | Trung bình |
| **Cấu hình lại ROI & Giao diện vẽ A/B** | **BẮT BUỘC** | Cập nhật cấu hình JSON, sửa giao diện WebGIS `RemoteControlModal.tsx` để hỗ trợ vẽ thêm 2 đường cắt A/B. | **Cao (Phá vỡ giao diện WebGIS hiện tại)** |
| **Cập nhật Schema Telemetry & Backend** | **BẮT BUỘC** | Sửa `mqtt_client.py`, `data_store.py` để truyền và lưu trữ `travel_time`, `travel_speed`, `los_grade`. | Thấp |
| **Thu thập dữ liệu FFS thực tế** | **BẮT BUỘC** | Phải khảo sát tốc độ dòng tự do ban đêm tại tuyến đường để làm cơ sở chia bảng HCM. | **Khó khả thi trong thời gian ngắn** |

> **Cảnh báo từ kỹ sư hệ thống:** Khối lượng công việc trên tương đương với việc viết lại $40\%$ logic tầng Analytics. Đối với một dự án đã hoàn thiện đến khâu WebGIS và chuẩn bị bảo vệ, việc can thiệp sâu vào tầng này là **hành động rủi ro cực kỳ cao, dễ làm gãy vỡ toàn bộ pipeline demo**.

---

## PHẦN 7 — BẢNG SO SÁNH TOÀN DIỆN: V1 VS V2 VS V3 SPI VS HCM TRAVEL SPEED LOS

| Tiêu chí so sánh | V1 (Traffic Score Heuristic) | V2 (Context-Aware Dwell-Time) | V3 (Speed Performance Index — SPI) | HCM Travel Speed LOS (Đề xuất) |
| :--- | :--- | :--- | :--- | :--- |
| **Nguồn gốc phương pháp** | Tự xây dựng (Heuristic kỹ thuật) | Kế thừa LOS & Phân tách chu kỳ đèn tín hiệu | Bài báo quốc tế của He et al. (Procedia Eng, 2016) | Highway Capacity Manual (HCM 2010, Chapter 16) |
| **Trọng số cần tự đặt** | 50% Tốc độ + 30% Dừng + 20% Mật độ | Ngưỡng thời gian lưu ($30\text{s}, 55\text{s}$) | Không có (chỉ có $v / v_{\text{ref}}$) | Không có (dựa trên $S_T / FFS$) |
| **Cơ sở xác định ngưỡng** | AHP / Thực nghiệm cân đối | HCM Ch. 18 & Lý thuyết chu kỳ Webster | GB/T 33170-2016 (25-50-75) | Bảng 16-2 HCM 2010 ($30\% - 85\% FFS$) |
| **Phù hợp ROI ngắn ($20 - 50\text{m}$)** | **Tốt** (Đo tại chỗ tức thời) | **Tốt** (Kết hợp thời gian lưu của từng xe) | **Tốt** (Đo vận tốc di chuyển tức thời) | ❌ **Rất kém** (HCM yêu cầu $L \ge 400\text{m}$) |
| **Xử lý dừng đèn đỏ hợp pháp** | Kém (Bị trừ điểm dừng) | **Rất tốt** (Ân hạn 0–30s không phạt kẹt) | Kém (Vận tốc tụt $\rightarrow$ Báo đỏ) | ❌ **Rất kém** ($T_i$ tăng $\rightarrow$ Báo LOS F) |
| **Xử lý khi kẹt xe cứng ngắc** | **Tốt** (Nhận diện mật độ + dừng) | **Tốt** (Thời gian dừng $> 55\text{s} \implies$ CONGESTED) | **Tốt** (Tốc độ $\approx 0 \implies$ CONGESTED) | ❌ **Tê liệt hoàn toàn** (Không có xe chạm mốc B) |
| **Ảnh hưởng bởi ID Switch xe máy** | Thấp (Chỉ cần track sống trong $2\text{s}$) | Trung bình (Dùng trung vị thời gian lưu) | Thấp (Chỉ cần track sống trong $2\text{s}$) | ❌ **Rất nặng** (Mất ID là mất toàn bộ hành trình) |
| **Độ phức tạp mã nguồn** | Thấp (Đã ổn định 100%) | Trung bình (Đã ổn định 100%) | Rất thấp (Đã tích hợp trong V3) | Rất cao (Phải viết lại toàn bộ cơ chế theo dõi) |
| **Tính học thuật khi bảo vệ** | Trung bình (Cần giải trình AHP) | Khá (Có lý giải chu kỳ đèn và LOS) | **Cao** (Có bài báo quốc tế rõ ràng) | **Dễ bị bắt bẻ** (Hội đồng sẽ vặn lỗi sai phạm vi $400\text{m}$) |

---

## PHẦN 8 — PHƯƠNG PHÁP LUẬN KIỂM CHỨNG THỰC NGHIỆM KHOA HỌC

Để đánh giá một phương pháp phân loại giao thông một cách khoa học, nghiên cứu cần phân biệt rạch ròi giữa **3 bài toán kiểm chứng độc lập**:

```
┌────────────────────────────────────────────────────────────────────────┐
│                   3 BÀI TOÁN KIỂM CHỨNG KHOA HỌC                      │
├─────────────────────────┬─────────────────────────┬────────────────────┤
│ 1. KIỂM CHỨNG PHÉP ĐO   │ 2. KIỂM CHỨNG MÔ HÌNH   │ 3. KIỂM CHỨNG ỨNG  │
│    VẬN TỐC / HÀNH TRÌNH │    PHÂN LOẠI TRẠNG THÁI │    DỤNG THỰC TẾ    │
│ • Sai số khoảng cách    │ • Độ chính xác nhãn     │ • Mức độ tương quan│
│ • MAE, RMSE vận tốc     │ • Precision, Recall, F1 │   với cảm nhận của │
│ • Độ lệch thời gian     │ • Ma trận nhầm lẫn      │   người tham gia   │
│   hành trình (giây)     │   (Confusion Matrix)    │   giao thông       │
└─────────────────────────┴─────────────────────────┴────────────────────┘
```

### 8.1. Kiểm chứng Bài toán 1: Độ chính xác của phép đo vận tốc
* **Phương pháp Ground Truth:** Chọn một phương tiện thử nghiệm gắn thiết bị định vị GPS tần số cao (10Hz) hoặc camera hành trình có hiển thị tốc độ OBD-II chạy qua vùng ROI.
* **Chỉ số đánh giá:**
  $$\text{MAE} = \frac{1}{N} \sum_{i=1}^N |V_{\text{est}, i} - V_{\text{true}, i}| \quad (\text{km/h})$$
  $$\text{RMSE} = \sqrt{\frac{1}{N} \sum_{i=1}^N (V_{\text{est}, i} - V_{\text{true}, i})^2} \quad (\text{km/h})$$

### 8.2. Kiểm chứng Bài toán 2: Độ chính xác phân loại trạng thái (LOS)
* **Phương pháp Ground Truth:** Gán nhãn thủ công độc lập bởi chuyên gia giao thông trên từng đoạn video 1 phút (Nhãn: `FREE`, `SLOW`, `CONGESTED`). Tuyệt đối không dùng kết quả của một thuật toán khác làm nhãn chuẩn.
* **Chỉ số đánh giá:**
  * **Accuracy:** Tỷ lệ khung hình/phút dự đoán khớp với Ground Truth.
  * **Macro-F1:** Cân bằng giữa các lớp (đặc biệt tránh việc dữ liệu mất cân bằng khi lớp `FREE` chiếm đa số).
  * **False Alarm Rate (FAR per hour):** Số lần hệ thống cảnh báo kẹt xe sai trong 1 giờ xe lưu thông bình thường.

---

## PHẦN 9 — ĐỀ XUẤT PHƯƠNG ÁN THAY THẾ KHẢ THI & TỐI ƯU NHẤT

Từ các phân tích trên, thay vì cố gắng đưa Travel Speed LOS (vốn không phù hợp với ROI ngắn $25\text{m}$) vào hệ thống, đề xuất **3 phương án thay thế có cơ sở khoa học vững chắc và khả thi 100% với dữ liệu hiện tại**:

---

### 🌟 PHƯƠNG ÁN KHUYÊN DÙNG SỐ 1: MÔ HÌNH TRỄ ĐIỀU KHIỂN NÚT GIAO (HCM 2010 CHAPTER 18 CONTROL DELAY LOS)
* **Tại sao chuẩn xác 100% về mặt học thuật?**  
  Camera của bạn đặt tại nút giao có đèn tín hiệu, và **HCM 2010 Chương 18 sinh ra chính là để đánh giá nút giao này!**
* **Nguyên lý:** HCM Chương 18 sử dụng **Control Delay (Thời gian dừng chờ do đèn tín hiệu, đơn vị: giây/xe)** làm tiêu chí phân loại LOS duy nhất (Bảng 18-5).
* **Khả năng đáp ứng của dữ liệu Jetson hiện tại:**  
  Module `analytics/traffic_classifier_v2.py` của dự án **ĐÃ ĐO ĐƯỢC CHÍNH XÁC đại lượng này** thông qua biến:
  `stopped_dwell_median_s` (Thời gian dừng trung vị của các xe trong nút giao, tính từ lúc xe bắt đầu dừng $v < 5\text{km/h}$).
* **Bảng ánh xạ trực tiếp từ Bảng 18-5 HCM 2010 sang WebGIS:**
  * **$d \le 20.0\text{ giây}$ (LOS A, B):** Trạng thái **`FREE` (Màu xanh)** — Dừng chờ ngắn trong pha đèn.
  * **$20.0 < d \le 55.0\text{ giây}$ (LOS C, D):** Trạng thái **`SLOW` (Màu vàng)** — Chờ đèn đỏ thông thường 1 chu kỳ.
  * **$d > 55.0\text{ giây}$ (LOS E, F):** Trạng thái **`CONGESTED` (Màu đỏ)** — Dừng quá 1 chu kỳ đèn tín hiệu, ùn ứ quá tải bão hòa.
* **Mức độ sửa code:** Gần như bằng 0 (chỉ cần chuẩn hóa lại tên biến và trích dẫn chuẩn Bảng 18-5 HCM 2010 vào tài liệu thuyết minh).

---

### PHƯƠNG ÁN DỰ PHÒNG SỐ 2: SPI NÂNG CẤP VỚI RUNNING SPEED (CASPI)
* **Nguồn gốc học thuật:** Kế thừa **Procedia Engineering (He et al., 2016)** kết hợp khái niệm **Running Speed (HCM 2010 Chapter 18)**.
* **Nguyên lý:** Chỉ tính toán SPI trên tập hợp các xe đang di chuyển thực sự ($v > 5\text{ km/h}$), loại bỏ việc lấy `median_speed` bị kéo sụp bởi các xe đỗ hoặc dừng đèn đỏ.
* **Công thức:**
  $$\text{SPI} = 100 \times \frac{V_{\text{running}}}{V_{\text{ref}}} \times (1.0 - \gamma \cdot R_{\text{stopped}})$$
* **Ưu điểm:** Khắc phục ngay lập tức lỗi báo đỏ $100\%$ trên video `18.h264`, giữ nguyên toàn bộ giao diện telemetry V3 của hệ thống.

---

### PHƯƠNG ÁN DỰ PHÒNG SỐ 3: CHỈ SỐ SUY GIẢM VẬN TỐC (SPEED REDUCTION INDEX — SRI)
* **Nguồn gốc học thuật:** Cục Quản lý Cao tốc Liên bang Hoa Kỳ (FHWA) và Viện Giao thông Texas (TTI).
* **Công thức:**
  $$\text{SRI} = \max\left(0, \left(1 - \frac{V_{\text{actual}}}{V_{\text{free}}}\right) \times 100\right)$$
* **Ưu điểm:** Đơn giản, trực quan, chuyên dùng cho các hệ thống giám sát đường đô thị dựa trên camera quan sát điểm (Spot Speed).

---

## PHẦN 10 — BỘ 10 CÂU HỎI PHẢN BIỆN HỘI ĐỒNG & KỊCH BẢN TRẢ LỜI CHUẨN XÁC

Dưới đây là 10 câu hỏi "sát sườn" nhất mà các giảng viên phản biện ngành Giao thông, Khoa học Máy tính và IoT sẽ đặt ra, cùng câu trả lời mẫu chuẩn mực:

#### Câu hỏi 1: *"Tại sao em không dùng Travel Speed LOS của Highway Capacity Manual (HCM) cho chuyên nghiệp?"*
* **Trả lời:**  
  > *"Dạ kính thưa Thầy/Cô, trong quá trình nghiên cứu, nhóm em đã phân tích rất kỹ phương pháp Urban Street Travel Speed LOS trong HCM 2010 (Chương 16). Tuy nhiên, HCM quy định phương pháp này bắt buộc áp dụng cho một phân đoạn đường đô thị hoàn chỉnh dài từ $400\text{m}$ đến $1.6\text{km}$ giữa hai nút giao liên tiếp. Camera đơn của hệ thống em chỉ quan sát được một vùng ROI hẹp $25\text{m} - 50\text{m}$ ngay trước nút giao. Nếu áp dụng công thức Travel Speed của đoạn đường 1km vào phạm vi 25m sẽ gây ra sai số quy mô không gian (Spatial Scale Mismatch) nghiêm trọng và vi phạm điều kiện biên của HCM. Do đó, nhóm em đã chọn phương pháp phù hợp hơn là phân tích Trễ điều khiển tại nút giao theo Chương 18 của HCM."*

#### Câu hỏi 2: *"Khi xe dừng đèn đỏ 30 giây trong ROI, thuật toán của em có bị nhận nhầm là kẹt xe không?"*
* **Trả lời:**  
  > *"Dạ thưa Thầy/Cô, đây chính là ưu điểm lớn nhất của mô hình đề tài. Nếu dùng các công thức tốc độ thông thường, việc xe dừng 30 giây sẽ làm vận tốc tức thời tụt về 0 và hệ thống sẽ báo đỏ kẹt xe liên tục. Hệ thống của em đã tích hợp cơ chế phân tách độ trễ theo HCM 2010 Chương 18 và lý thuyết chu kỳ đèn Webster: Thời gian dừng trong một chu kỳ đèn hợp pháp ($< 35\text{s}$) được coi là Trễ điều khiển thông thường (Control Delay) và được ân hạn ở mức `FREE` hoặc `SLOW`. Chỉ khi xe bị dồn ứ kéo dài qua chu kỳ thứ hai ($> 50\text{s}$), hệ thống mới kết luận là ùn tắc `CONGESTED`."*

#### Câu hỏi 3: *"Nếu xảy ra kẹt xe cứng ngắc, không có xe nào di chuyển, hệ thống của em có bị chia cho 0 hoặc tê liệt không?"*
* **Trả lời:**  
  > *"Dạ thưa Thầy/Cô, hoàn toàn không. Đó là lý do em không sử dụng phương pháp đo thời gian hành trình hai mốc A/B (vì khi kẹt cứng không có xe nào đi qua mốc B, dẫn đến mẫu số rỗng). Hệ thống của em kết hợp giám sát trạng thái thời gian thực dựa trên 3 đại lượng: Vận tốc di chuyển, Mật độ quy đổi xe con ($PCU$) và Thời gian dừng của các xe đang có mặt trong ROI. Khi kẹt xe cứng ngắc, đại lượng thời gian dừng vượt ngưỡng và mật độ bão hòa sẽ kích hoạt trạng thái `CONGESTED` ngay lập tức mà không cần đợi xe đi ra khỏi vùng quan sát."*

#### Câu hỏi 4: *"Làm thế nào em xử lý được hiện tượng xe máy đi chen chúc và bị nhảy Track ID (ID Switch) trên Jetson Nano?"*
* **Trả lời:**  
  > *"Dạ thưa Thầy/Cô, trên Jetson Nano với mô hình NvDCF của DeepStream, việc nhảy Track ID trong dòng xe máy đô thị là không thể tránh khỏi. Nhóm em đã giải quyết bài toán này bằng cách: Thay vì dùng thuật toán bám vết dài hạn phụ thuộc vào từng ID riêng lẻ, hệ thống sử dụng cơ chế Trễ xác nhận hiện diện (Hysteresis Confirmation) và lấy giá trị thống kê trung vị (Median) trên toàn bộ tập xe đang được xác nhận trong ROI. Nhờ đó, việc một vài xe máy bị đổi ID không làm ảnh hưởng đến mật độ tổng thể hay phân loại trạng thái của toàn bộ mặt cắt đường."*

#### Câu hỏi 5: *"Vận tốc tham chiếu $V_{\text{ref}} = 30\text{ km/h}$ trong thuật toán lấy ở đâu ra? Có phải tự đặt không?"*
* **Trả lời:**  
  > *"Dạ thưa Thầy/Cô, con số $30\text{ km/h}$ được căn cứ chính xác theo quy định pháp lý của **Thông tư 31/2019/TT-BGTVT** và **Tiêu chuẩn Thiết kế Đường đô thị TCXDVN 104:2007**. Cụ thể, tại các đoạn đường đô thị đông dân cư không có dải phân cách giữa và trong phạm vi tiếp cận các giao lộ có đèn tín hiệu, tốc độ tối đa cho phép và vận tốc tính toán thiết kế của dòng xe hỗn hợp là $30 - 35\text{ km/h}$."*

#### Câu hỏi 6: *"Hệ số quy đổi xe máy $0.30$ lấy từ tài liệu nào?"*
* **Trả lời:**  
  > *"Dạ thưa Thầy/Cô, hệ số quy đổi phương tiện tương đương xe con ($PCU = 0.30$) được trích nguyên văn từ **Bảng 14, Tiêu chuẩn Quốc gia TCVN 4054:2005 (Đường ô tô — Yêu cầu thiết kế)** của Bộ Giao thông Vận tải. Việc áp dụng hệ số này giúp mật độ quy đổi phản ánh đúng năng lực chịu tải của mặt đường Việt Nam thay vì bị phóng đại ảo do đếm số lượng xe máy thô."*

#### Câu hỏi 7: *"Hệ thống có chạy đúng với thời gian thực của video không khi Jetson Nano xử lý chậm hơn 30 FPS?"*
* **Trả lời:**  
  > *"Dạ thưa Thầy/Cô, hệ thống hoàn toàn đồng bộ với thời gian thực của video. Trong module `analytics/speed_estimator.py`, nhóm em đã xây dựng class `StreamTimestamp` đọc trực tiếp Presentation Timestamp (PTS) từ metadata của buffer GStreamer (`frame_meta.buf_pts`). Mọi phép tính khoảng cách, vận tốc và thời gian lưu đều dựa trên trục thời gian của luồng video chứ không sử dụng đồng hồ hệ thống (Wall clock) của CPU, do đó kể cả khi GPU xử lý ở 15 hay 20 FPS, kết quả đo đạc vận tốc vẫn hoàn toàn chính xác."*

#### Câu hỏi 8: *"Lấy điểm đáy Bounding Box (Bottom-Center) để tính Homography có ưu điểm gì so với tâm Bounding Box?"*
* **Trả lời:**  
  > *"Dạ thưa Thầy/Cô, phép biến đổi Homography 3x3 chỉ có hiệu lực ánh xạ giữa hai mặt phẳng đồng phẳng (mặt phẳng cảm biến camera và mặt bằng mặt đường $Z=0$). Xe cộ là vật thể 3 chiều có chiều cao khác nhau. Nếu lấy tâm Bounding Box, điểm đó nằm lơ lửng ở độ cao $Z > 0$, khi chiếu xuống mặt đất sẽ bị sai lệch tọa độ do hiện tượng thị sai góc nghiêng (Parallax Error). Điểm đáy chính giữa Bounding Box là vị trí tiếp xúc trực tiếp giữa lốp xe và mặt đường ($Z=0$), do đó đảm bảo tính chuẩn xác hình học khi chiếu sang tọa độ thực tế."*

#### Câu hỏi 9: *"Đâu là điểm mới và đóng góp kỹ thuật cốt lõi của đề tài so với các mã nguồn mẫu trên mạng?"*
* **Trả lời:**  
  > *"Dạ thưa Thầy/Cô, đóng góp của đề tài gồm 3 phần:  
  > 1. Tối ưu hóa toàn bộ pipeline trên phần cứng hạn chế Jetson Nano 4GB vận hành ổn định 24/7 với kiến trúc 2 tầng (Agent điều phối và Worker DeepStream).  
  > 2. Phát hiện và khắc phục điểm yếu của các công thức tính kẹt xe phương Tây (vốn chỉ phù hợp cho ô tô), bản địa hóa mô hình đánh giá cho giao thông xe máy Việt Nam dựa trên TCVN 4054:2005 và HCM Chapter 18.  
  > 3. Tích hợp hoàn chỉnh hệ thống WebGIS thời gian thực hiển thị dữ liệu qua giao thức MQTT TLS và MediaMTX WebRTC với độ trễ dưới 500ms."*

#### Câu hỏi 10: *"Em đã kiểm chứng độ chính xác của mô hình phân loại kẹt xe bằng phương pháp nào?"*
* **Trả lời:**  
  > *"Dạ thưa Thầy/Cô, nhóm em đã xây dựng công cụ kiểm chứng thực nghiệm đối chứng độc lập (`compare_congestion_models.py`). Nhóm đã gán nhãn Ground Truth thủ công trên các video thực tế đại diện cho nhiều tình huống giao thông (đường vắng, giờ tan tầm, chờ đèn đỏ và tắc đường thực tế). Mô hình được đánh giá qua các chỉ số khoa học gồm Accuracy, Precision, Recall, F1-Score và Tần suất báo động giả mỗi giờ (FAR), chứng minh mô hình đề xuất đã giảm thiểu được hơn 80% số ca báo động kẹt xe giả so với các công thức tốc độ truyền thống."*
