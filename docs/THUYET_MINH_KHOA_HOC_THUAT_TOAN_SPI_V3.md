# TÀI LIỆU THUYẾT MINH KHOA HỌC: MÔ HÌNH ĐÁNH GIÁ ÙN TẮC GIAO THÔNG DỰA TRÊN CHỈ SỐ HIỆU NĂNG VẬN TỐC (SPEED PERFORMANCE INDEX — SPI) VÀ CẢI TIẾN THÍCH ỨNG ĐÔ THỊ (CASPI)

> **Ghi chú phiên bản:** Nội dung CASPI bên dưới là đề xuất nghiên cứu trước đó,
> không phải đặc tả SPI v3 đang triển khai. Đọc [hướng dẫn SPI v3](./traffic_classifier_v3.md)
> để biết công thức, cấu hình WebGIS/Jetson và giới hạn hiện hành. V3 dùng
> trung vị các tốc độ hợp lệ (kể cả xe dừng), không có hệ số phạt gamma,
> không tự đặt tốc độ tham chiếu 30 km/h. Những nhận định về “căn cứ pháp lý”,
> tham số Webster và dữ liệu thực nghiệm bên dưới chưa được xác minh trong
> đợt triển khai v3; không dùng chúng như bằng chứng kiểm định của phiên bản này.

---

## MỤC LỤC
1. [Tổng quan & Bối cảnh học thuật](#1-tổng-quan--bối-cảnh-học-thuật)
2. [Cơ sở khoa học của Mô hình SPI nguyên bản (V3 Baseline)](#2-cơ-sở-khoa-học-của-mô-hình-spi-nguyên-bản-v3-baseline)
3. [Phân tích thực nghiệm & Hạn chế của SPI nguyên bản trên Video 18.h264](#3-phân-tích-thực-nghiệm--hạn-chế-của-spi-nguyên-bản-trên-video-18h264)
4. [Mô hình Đề xuất: SPI Thích ứng Ngữ cảnh Đô thị (Context-Adaptive SPI — CASPI)](#4-mô-hình-đề-xuất-spi-thích-ứng-ngữ-cảnh-đô-thị-context-adaptive-spi--caspi)
5. [Căn cứ Pháp lý & Khoa học của Các Tham số Kỹ thuật](#5-căn-cứ-pháp-lý--khoa-học-của-các-tham-số-kỹ-thuật)
6. [Phương pháp luận Đánh giá Thực nghiệm (Evaluation Benchmark)](#6-phương-pháp-luận-đánh-giá-thực-nghiệm-evaluation-benchmark)
7. [Danh mục Tài liệu Tham khảo (References)](#7-danh-mục-tài-liệu-tham-khảo-references)

---

## 1. TỔNG QUAN & BỐI CẢNH HỌC THUẬT

Trong các hệ thống giám sát và điều hành giao thông thông minh (Intelligent Transportation Systems — ITS), việc phân loại trạng thái mặt đường thời gian thực từ dữ liệu camera là bài toán cốt lõi. Đối với các thiết bị xử lý tại biên (Edge AI) có tài nguyên phần cứng giới hạn như **NVIDIA Jetson Nano 4GB**, giải thuật phân loại ùn tắc đòi hỏi phải đáp ứng đồng thời ba yêu cầu:
1. **Tính thời gian thực:** Độ trễ tính toán $< 5\text{ ms/frame}$ để không ảnh hưởng đến FPS của mô hình thị giác máy tính (YOLOv11 + NvDCF Tracker).
2. **Tính giải thích được (Explainable AI — XAI):** Trạng thái cảnh báo kẹt xe phải dựa trên các đại lượng vật lý rõ ràng (vận tốc, mật độ, tỷ lệ dừng), không phải là mô hình hộp đen khó kiểm chứng.
3. **Tính chuẩn tắc học thuật:** Thuật toán phải có nguồn gốc từ các bài báo khoa học quốc tế hoặc tiêu chuẩn giao thông được công nhận rộng rãi.

---

## 2. CƠ SỞ KHOA HỌC CỦA MÔ HÌNH SPI NGUYÊN BẢN (V3 BASELINE)

### 2.1. Nguồn gốc công bố quốc tế
Chỉ số Hiệu năng Vận tốc (**Speed Performance Index — SPI**) là thước đo hiệu quả vận hành mạng lưới giao thông được đề xuất và áp dụng trong các công trình nghiên cứu:
* **Công trình 1:** He, F., Yan, X., Liu, Y., & Ma, L. (2016). *"A Traffic Congestion Assessment Method for Urban Road Networks Based on Speed Performance Index"*, **Procedia Engineering**, Elsevier, 137, 425-433.
* **Công trình 2:** Zhang, Y., et al. (2023). *"An expressway traffic congestion measurement under the influence of service areas"*, **PLOS ONE**, 18(1), e0279966.
* **Tiêu chuẩn Kỹ thuật:** Chuẩn hóa theo Tiêu chuẩn Quốc gia về Đánh giá Trạng thái Giao thông Đô thị **GB/T 33170-2016**.

### 2.2. Công thức toán học SPI nguyên bản
$$\text{SPI} = 100 \times \frac{v_{\text{avg}}}{v_{\text{ref}}}$$

*Trong đó:*
* $v_{\text{avg}}$: Vận tốc trung bình thực tế của các phương tiện trong đoạn đường quan sát (km/h).
* $v_{\text{ref}}$: Vận tốc tham chiếu quy chuẩn của tuyến đường (km/h) (thường là tốc độ giới hạn thiết kế hoặc tốc độ dòng tự do).

### 2.3. Bảng phân cấp trạng thái theo chuẩn công bố (He et al., 2016)
Bài báo gốc phân định chất lượng lưu thông thành 4 cấp độ, được ánh xạ vào 3 trạng thái của WebGIS như sau:

| Dải giá trị $\text{SPI}$ | Cấp độ giao thông (SPI Level) | Trạng thái hiển thị (WebGIS) | Ý nghĩa giao thông |
| :---: | :---: | :---: | :--- |
| **$75 < \text{SPI} \le 100$** | `VERY_SMOOTH` | **`FREE` (Xanh)** | Dòng xe lưu thông rất tốt, vận tốc đạt trên 75% tốc độ thiết kế |
| **$50 < \text{SPI} \le 75$** | `SMOOTH` | **`FREE` (Xanh)** | Dòng xe ổn định, lưu thông bình thường |
| **$25 < \text{SPI} \le 50$** | `MILD_CONGESTION` | **`SLOW` (Vàng)** | Bắt đầu có xung đột dòng xe, vận tốc giảm còn 25–50% |
| **$0 \le \text{SPI} \le 25$** | `HEAVY_CONGESTION` | **`CONGESTED` (Đỏ)** | Kẹt xe nghiêm trọng, vận tốc sụt giảm dưới 25% |

---

## 3. PHÂN TÍCH THỰC NGHIỆM & HẠN CHẾ CỦA SPI NGUYÊN BẢN TRÊN VIDEO 18.h264

### 3.1. Dữ liệu thực nghiệm thực tế từ Camera Edge-110
Khi triển khai công thức V3 nguyên bản trên thiết bị Jetson Nano với nguồn video `18.h264` (đoạn nút giao đường Lê Đức Thọ), cơ sở dữ liệu `history.db` ghi nhận các chuỗi telemetry liên tục như sau:

$$\begin{aligned}
\text{13:37:} \quad & v_{\text{avg}} = 2.2\text{ km/h}, \quad N = 9\text{ xe}, \quad R_{\text{stop}} = 21.2\% \implies \text{SPI} \approx 5.5 \implies \mathbf{CONGESTED} \\
\text{13:38:} \quad & v_{\text{avg}} = 7.5\text{ km/h}, \quad N = 8\text{ xe}, \quad R_{\text{stop}} = 17.0\% \implies \text{SPI} \approx 18.7 \implies \mathbf{CONGESTED} \\
\text{13:39:} \quad & v_{\text{avg}} = 3.6\text{ km/h}, \quad N = 9\text{ xe}, \quad R_{\text{stop}} = 29.3\% \implies \text{SPI} \approx 9.0 \implies \mathbf{CONGESTED} \\
\text{13:40:} \quad & v_{\text{avg}} = 1.2\text{ km/h}, \quad N = 7\text{ xe}, \quad R_{\text{stop}} = 28.0\% \implies \text{SPI} \approx 3.0 \implies \mathbf{CONGESTED} \\
\text{13:41:} \quad & v_{\text{avg}} = 8.2\text{ km/h}, \quad N = 20\text{ xe}, \quad R_{\text{stop}} = 11.2\% \implies \text{SPI} \approx 20.5 \implies \mathbf{CONGESTED}
\end{aligned}$$

Hệ thống trả về kết quả **$100\%$ là `CONGESTED`**, dù quan sát thực tế bằng mắt thường cho thấy dòng xe máy vẫn đang trôi qua nút giao sau các nhịp đèn tín hiệu.

### 3.2. Ba nguyên nhân dẫn đến sự thất bại của SPI nguyên bản tại nút giao
1. **Đánh đồng "chờ đèn đỏ" với "kẹt xe" (Signal Delay vs Congestion Delay):**  
   Bài báo của He et al. (2016) áp dụng cho đường mở (mid-block) hoặc cao tốc. Khi đặt vào camera nút giao có đèn tín hiệu, các phương tiện bắt buộc phải dừng chờ đèn đỏ hợp pháp. Việc tính thời gian dừng này vào công thức SPI khiến mọi ngã tư đều bị gắn nhãn "kẹt xe nặng" trong toàn bộ pha đèn đỏ.
2. **Sai số do lấy Vận tốc Trung vị (`median_speed`):**  
   Khi trong vùng ROI có một vài xe máy đỗ lề đường hoặc đang dừng chờ ở đầu vạch, việc lấy trung vị của toàn bộ các xe khiến $V_{\text{median}}$ sụp đổ về gần $0\text{ km/h}$ (thực tế có lúc ghi nhận $\text{SPI} = 0.1$), làm tê liệt phép đo.
3. **Vận tốc tham chiếu $V_{\text{ref}}$ bị đặt quá cao:**  
   $V_{\text{ref}} = 40.0\text{ km/h}$ không phản ánh đúng vận tốc tiếp cận giao lộ trong đô thị Việt Nam.

---

## 4. MÔ HÌNH ĐỀ XUẤT: SPI THÍCH ỨNG NGỮ CẢNH ĐÔ THỊ (CONTEXT-ADAPTIVE SPI — CASPI)

Để hoàn thiện mô hình V3 mà vẫn giữ trọn vẹn tính chuẩn mực học thuật, đề tài đề xuất mô hình **CASPI** tích hợp lý thuyết trễ nút giao từ **Highway Capacity Manual (HCM 2010)** và lý thuyết chu kỳ đèn tín hiệu của **Webster (1958)**.

### 4.1. Bước 1: Tính Vận tốc Hành trình Thực tế (Running Speed — $V_{\text{run}}$)
Theo định nghĩa chuẩn tại **Chương 18, HCM 2010**: Để đánh giá hiệu quả vận hành của dòng xe tại nút giao, vận tốc phải được đo trên tập hợp các phương tiện đang thực sự di chuyển ($S_{\text{moving}}$ có $v_i > 5.0\text{ km/h}$ và `has_moved=True`), loại trừ các phương tiện đỗ tĩnh hoặc dừng chết:

$$V_{\text{run}} = \begin{cases} 
\frac{1}{|S_{\text{moving}}|} \sum_{i \in S_{\text{moving}}} v_i, & \text{nếu } |S_{\text{moving}}| > 0 \\
0, & \text{nếu toàn bộ xe dừng cứng } (|S_{\text{moving}}| = 0)
\end{cases}$$

### 4.2. Bước 2: Tính Chỉ số SPI Hành trình cơ sở ($\text{SPI}_{\text{run}}$)
$$\text{SPI}_{\text{run}} = 100 \times \frac{V_{\text{run}}}{V_{\text{ref}}}$$
*(Với $V_{\text{ref}} = 30.0\text{ km/h}$ theo vận tốc thiết kế nút giao đô thị).*

### 4.3. Bước 3: Hiệu chỉnh Phạt Trễ Dừng Đèn Tín hiệu (Signal Context Adjustment)
Tích hợp tỷ lệ phương tiện dừng bánh $R_{\text{stop}} \in [0.0, 1.0]$:

$$\text{SPI}_{\text{composite}} = \text{SPI}_{\text{run}} \times \left(1.0 - \gamma \times R_{\text{stop}}\right)$$

*Trong đó hệ số phạt $\gamma$ được xác lập dựa trên lý thuyết chu kỳ đèn Webster:*
* **Tại nút giao có đèn tín hiệu (`signalized`):**  
  * Nếu thời gian dừng trong chu kỳ hợp pháp ($t_{\text{stop}} \le 35\text{s}$): Áp dụng **$\gamma = 0.25$** (Phạt nhẹ, phản ánh tỷ lệ pha đèn đỏ thông thường $r/C$).
  * Nếu thời gian dừng kéo dài qua nhiều chu kỳ ($t_{\text{stop}} > 50\text{s}$): Áp dụng **$\gamma = 0.70$** (Phạt nặng do ùn ứ quá tải bão hòa $v/c > 1.0$).
* **Đoạn đường thông thường không đèn (`midblock`):** Áp dụng **$\gamma = 0.60$**.

### 4.4. Bước 4: Quy tắc Phân cấp Trạng thái
Kế thừa nguyên bản ngưỡng phân cấp từ bài báo quốc tế của He et al. (2016):
$$\text{Trạng thái} = \begin{cases}
\mathbf{FREE} & \text{nếu } \text{SPI}_{\text{composite}} > 50.0 \\
\mathbf{SLOW} & \text{nếu } 25.0 < \text{SPI}_{\text{composite}} \le 50.0 \\
\mathbf{CONGESTED} & \text{nếu } \text{SPI}_{\text{composite}} \le 25.0
\end{cases}$$

---

## 5. CĂN CỨ PHÁP LÝ & KHOA HỌC CỦA CÁC THAM SỐ KỸ THUẬT

Mọi con số sử dụng trong công thức CASPI đều có địa chỉ tham chiếu khoa học và pháp lý minh bạch:

| Tham số | Giá trị định chuẩn | Căn cứ pháp lý & Nguồn gốc học thuật |
| :--- | :---: | :--- |
| **Chỉ số gốc $\text{SPI}$** | $100 \times \frac{v}{v_{\text{ref}}}$ | Công trình của **He et al. (Procedia Engineering, 2016)** và **PLOS ONE (2023)**. |
| **Vận tốc tham chiếu $V_{\text{ref}}$** | **$30.0\text{ km/h}$** | **Thông tư 31/2019/TT-BGTVT** (Điều 6 & 7) & **TCXDVN 104:2007**: Tốc độ tối đa cho phép của xe gắn máy trong đô thị và vận tốc tính toán tại vùng tiếp cận giao lộ. |
| **Vận tốc hành trình $V_{\text{run}}$** | Vận tốc xe đang chạy | **HCM 2010 (Chương 18: Signalized Intersections)**: Khái niệm Running Speed loại bỏ thời gian trễ do dừng đèn đỏ (*Control Delay*). |
| **Ngưỡng xe dừng $V_{\text{stop}}$** | **$5.0\text{ km/h}$** | **FHWA & ITE (Institute of Transportation Engineers)**: Vận tốc tương đương người đi bộ ($1.4\text{ m/s}$), dưới ngưỡng này phương tiện được coi là dừng bánh/bò nhích. |
| **Hệ số phạt dừng $\gamma$** | **$0.25$ và $0.70$** | **Lý thuyết Chu kỳ Đèn Webster (TRRL Paper No. 39)**: Tương ứng tỷ lệ pha đỏ trên chu kỳ $r/C \approx 25 - 35\%$ ở đô thị Việt Nam. |
| **Ngưỡng phân cấp 25 - 50** | $25.0$ và $50.0$ | **Tiêu chuẩn Quốc gia GB/T 33170-2016** và phân cấp dịch vụ LOS của He et al. (2016). |

---

## 6. PHƯƠNG PHÁP LUẬN ĐÁNH GIÁ THỰC NGHIỆM (EVALUATION BENCHMARK)

Để chứng minh tính ưu việt của mô hình cải tiến CASPI so với mô hình SPI nguyên bản, đề tài xây dựng quy trình kiểm chứng thực nghiệm trên bộ dữ liệu gồm **5 – 10 video giao thông thực tế**:

### 6.1. Thiết kế Kịch bản Thực nghiệm Đa dạng
Bộ video kiểm thử bao phủ toàn bộ các pha giao thông điển hình:
1. **Kịch bản A (Free-Flow):** Đường vắng, lưu thông tự do ($V > 25\text{ km/h}$).
2. **Kịch bản B (Mixed Rush Hour):** Giờ tan tầm, xe máy đông đúc nhưng duy trì trôi đều ($V \approx 18 - 22\text{ km/h}$).
3. **Kịch bản C (Signal Queue):** Dừng chờ đèn đỏ trật tự tại ngã tư trong vòng 1 chu kỳ ($< 30\text{s}$).
4. **Kịch bản D (Transition Flow):** Dòng xe di chuyển chậm dần khi vào giao lộ ($V \approx 10 - 15\text{ km/h}$).
5. **Kịch bản E (Gridlock Congestion):** Xe dừng bánh dồn ứ kéo dài $> 1\text{ phút}$, xung đột giao cắt.
6. **Kịch bản F (Curb Parking):** Có phương tiện đỗ tĩnh bên mép đường.

### 6.2. Bộ Chỉ số Đo lường Hiệu năng (Performance Metrics)
Dựa trên ma trận nhầm lẫn đối chiếu với nhãn chuẩn thực tế quan sát (**Ground Truth**):

$$\text{Accuracy} = \frac{TP + TN}{TP + TN + FP + FN} \times 100\%$$
$$\text{Precision} = \frac{TP}{TP + FP} \times 100\% \quad (\text{Độ tin cậy khi cảnh báo kẹt xe})$$
$$\text{Recall} = \frac{TP}{TP + FN} \times 100\% \quad (\text{Khả năng phát hiện kẹt xe thực tế})$$
$$F_1\text{-score} = 2 \times \frac{\text{Precision} \times \text{Recall}}{\text{Precision} + \text{Recall}}$$
$$\text{FAR} = \frac{FP}{\text{Tổng thời gian quan sát (giờ)}} \quad (\text{Tần suất báo động giả mỗi giờ})$$

Công cụ thực thi tự động có sẵn tại [`tools/compare_congestion_models.py`](file:///d:/Project/Project/tools/compare_congestion_models.py) để xuất trực tiếp bảng số liệu ra định dạng CSV và đồ thị trực quan cho báo cáo.

---

## 7. DANH MỤC TÀI LIỆU THAM KHẢO (REFERENCES)

1. **He, F., Yan, X., Liu, Y., & Ma, L. (2016)**, "A Traffic Congestion Assessment Method for Urban Road Networks Based on Speed Performance Index", *Procedia Engineering*, vol. 137, pp. 425-433.
2. **Transportation Research Board (TRB) (2010)**, *Highway Capacity Manual (HCM 2010)*, National Research Council, Washington, D.C., USA. (Chapter 16: Urban Streets, Chapter 18: Signalized Intersections).
3. **Bộ Giao thông Vận tải (2019)**, *Thông tư số 31/2019/TT-BGTVT: Quy định về tốc độ và khoảng cách an toàn của xe cơ giới, xe máy chuyên dùng tham gia giao thông đường bộ*, Hà Nội.
4. **Bộ Xây dựng (2007)**, *Tiêu chuẩn Xây dựng Việt Nam TCXDVN 104:2007: Đường đô thị — Yêu cầu thiết kế*, Hà Nội.
5. **Webster, F. V. (1958)**, *Traffic Signal Settings*, Road Research Technical Paper No. 39, Road Research Laboratory, HMSO, London.
6. **Zhang, Y., et al. (2023)**, "An expressway traffic congestion measurement under the influence of service areas", *PLOS ONE*, 18(1), e0279966.
7. **General Administration of Quality Supervision, Inspection and Quarantine of PR China (2016)**, *GB/T 33170-2016: Evaluation Method for Urban Road Traffic State*, National Standards of the People's Republic of China.
