# TÀI LIỆU KHOA HỌC: PHƯƠNG PHÁP LUẬN THIẾT KẾ MÔ HÌNH ĐÁNH GIÁ ÙN TẮC GIAO THÔNG ĐA TIÊU CHÍ (MCDM-AHP) TRÊN THIẾT BỊ BIÊN JETSON NANO

---

## 1. TỔNG QUAN VÀ ĐẶT VẤN ĐỀ

Trong các hệ thống giám sát giao thông thông minh (ITS) truyền thống tại các nước phát triển, việc đánh giá ùn tắc thường dựa trên lưu lượng xe ô tô đơn nhất (lane-based flow) hoặc phương pháp cắt vạch ảo (tripwire). Tuy nhiên, tại các đô thị lớn ở Việt Nam (như Hà Nội và TP. Hồ Chí Minh), dòng giao thông mang đặc trưng **hỗn hợp phi làn (non-lane-based heterogeneous traffic)** với hơn $85\%$ phương tiện là xe hai bánh (mô tô, xe gắn máy).

Xe máy có kích thước nhỏ và đặc tính di chuyển "mao dẫn" (seeping flow) qua các khoảng hở mặt đường hẹp. Nếu áp dụng các mô hình đánh giá dựa trên mật độ số xe thuần túy ($veh/km$), một luồng xe máy đông đúc nhưng đang di chuyển thông suốt ở vận tốc $20 - 25\text{ km/h}$ sẽ liên tục bị hệ thống gắn nhãn nhầm là **Ùn tắc nghiêm trọng (False Alarm)**.

Để khắc phục hiện tượng trên trong điều kiện tài nguyên tính toán hạn chế của thiết bị biên NVIDIA Jetson Nano 4GB, đề tài đề xuất **Mô hình Đánh giá Trạng thái Giao thông Đa tiêu chí (Multi-Criteria Traffic State Evaluation Model)** tích hợp giữa:
1. Chuẩn hóa hình học phương tiện theo **Tiêu chuẩn Quốc gia TCVN 4054:2005**.
2. Phân cấp mức độ dịch vụ **Level of Service (LOS)** theo Sổ tay Năng lực Thông hành **HCM 2010**.
3. Phương pháp toán học **Phân tích Thứ bậc AHP (Analytic Hierarchy Process)** của GS. Thomas L. Saaty để lượng hóa bộ trọng số tối ưu.

---

## 2. CƠ SỞ ĐỊNH CHUẨN ĐƠN VỊ XE CON TƯƠNG ĐƯƠNG (PCU / PCE)

Theo quy định tại **Tiêu chuẩn Quốc gia TCVN 4054:2005 (Đường ô tô — Yêu cầu thiết kế)**, bảng hệ số quy đổi phương tiện sang đơn vị xe con tiêu chuẩn (**Passenger Car Equivalent - PCE / Passenger Car Unit - PCU**) được áp dụng:

| Loại phương tiện (Class) | Hệ số quy đổi ($PCU$) | Căn cứ pháp lý / Kỹ thuật |
| :--- | :---: | :--- |
| **Xe mô tô, xe gắn máy** | **$0.30$** | TCVN 4054:2005 (Bảng 14) |
| **Xe đạp** | **$0.20$** | TCVN 4054:2005 |
| **Ô tô con (Car)** | **$1.00$** | Phương tiện chuẩn quy chiếu |
| **Xe tải trung / tải nhẹ** | **$1.80$** | TCVN 4054:2005 |
| **Xe buýt / Xe khách** | **$2.00$** | TCVN 4054:2005 |

### Công thức tính Mật độ quy đổi ($k_{\text{pce}}$):
$$\text{PCE Count} = \sum_{i \in \text{Classes}} N_i \times PCU_i$$
$$k_{\text{pce}} = \frac{\text{PCE Count}}{L_{\text{km}} \times N_{\text{lane}}} \quad (\text{PCU/km/làn})$$

*Trong đó:* $L_{\text{km}}$ là chiều dài đoạn đường phân tích (km), $N_{\text{lane}}$ là số làn xe quan sát.

---

## 3. PHƯƠNG PHÁP XÁC ĐỊNH BỘ TRỌNG SỐ BẰNG AHP (ANALYTIC HIERARCHY PROCESS)

Để tính toán **Điểm số tắc nghẽn (Congestion Score $S \in [0, 100]$)** phản ánh trung thực trạng thái mặt đường, hệ thống kết hợp 3 tiêu chí động học và không gian:
* **$C_1$ (Vận tốc dòng xe - $V$):** Đại diện cho tốc độ giải phóng mặt cắt đường.
* **$C_2$ (Tỷ lệ xe dừng bánh - $R_{\text{stop}}$):** Đại diện cho sự tắc nghẽn vật lý và dồn ứ cục bộ.
* **$C_3$ (Mật độ quy đổi - $k_{\text{pce}}$):** Đại diện cho mức độ chiếm dụng không gian mặt đường.

### 3.1. Thiết lập Ma trận so sánh cặp (Pairwise Comparison Matrix)
Dựa trên nguyên lý dòng mao dẫn đô thị (nghiên cứu của TS. Vũ Anh Tuấn, ĐH Việt - Đức): *Dòng xe máy có thể chấp nhận mật độ rất cao nhưng vẫn lưu thông tốt nếu duy trì được vận tốc, và hiện tượng ùn tắc chỉ thực sự hình thành khi các phương tiện phanh dừng bánh nối đuôi nhau.* Do đó, mức độ quan trọng được xếp bậc:
$$\text{Vận tốc } (C_1) \succ \text{Tỷ lệ xe dừng } (C_2) \succ \text{Mật độ chiếm dụng } (C_3)$$

Theo thang điểm 9 mức của Saaty (1980), ta xác lập ma trận so sánh cặp $A = [a_{ij}]_{3 \times 3}$:

$$A = \begin{bmatrix}
a_{11} & a_{12} & a_{13} \\
a_{21} & a_{22} & a_{23} \\
a_{31} & a_{32} & a_{33}
\end{bmatrix} = \begin{bmatrix}
1 & \frac{5}{3} & \frac{5}{2} \\
\frac{3}{5} & 1 & \frac{3}{2} \\
\frac{2}{5} & \frac{2}{3} & 1
\end{bmatrix} \approx \begin{bmatrix}
1.000 & 1.667 & 2.500 \\
0.600 & 1.000 & 1.500 \\
0.400 & 0.667 & 1.000
\end{bmatrix}$$

### 3.2. Tính toán Vector trọng số ưu tiên ($w$)
Chuẩn hóa ma trận theo phương pháp trung bình hình học từng hàng (Geometric Mean):
1. Tích từng hàng:
   * $\Pi_1 = 1.000 \times 1.667 \times 2.500 = 4.1675 \implies \sqrt[3]{\Pi_1} = 1.6094$
   * $\Pi_2 = 0.600 \times 1.000 \times 1.500 = 0.9000 \implies \sqrt[3]{\Pi_2} = 0.9655$
   * $\Pi_3 = 0.400 \times 0.667 \times 1.000 = 0.2668 \implies \sqrt[3]{\Pi_3} = 0.6438$
   * Tổng: $\sum \sqrt[3]{\Pi_i} = 1.6094 + 0.9655 + 0.6438 = 3.2187$

2. Chuẩn hóa thành Vector trọng số:
   $$w_1 = \frac{1.6094}{3.2187} = \mathbf{0.500} \quad (50\%)$$
   $$w_2 = \frac{0.9655}{3.2187} = \mathbf{0.300} \quad (30\%)$$
   $$w_3 = \frac{0.6438}{3.2187} = \mathbf{0.200} \quad (20\%)$$

Ta thu được chính xác bộ trọng số: $\mathbf{w = [0.50, 0.30, 0.20]^T}$.

### 3.3. Kiểm định tính nhất quán toán học (Consistency Test)
* Nhân ma trận: $A \cdot w = [1.500, 0.900, 0.600]^T = 3.000 \cdot w$
* Giá trị riêng cực đại: $\lambda_{\max} = 3.000$
* Chỉ số nhất quán (Consistency Index):
  $$CI = \frac{\lambda_{\max} - n}{n - 1} = \frac{3.000 - 3}{3 - 1} = \mathbf{0.000}$$
* Với $n = 3$, chỉ số ngẫu nhiên chuẩn (Random Index) $RI = 0.58$:
  $$CR = \frac{CI}{RI} = \frac{0.000}{0.58} = \mathbf{0.000} < 0.10$$
* **Kết luận:** Tỷ số nhất quán $CR = 0 < 0.10$, chứng minh bộ trọng số thỏa mãn tính nhất quán hoàn hảo về mặt toán học.

---

## 4. XÂY DỰNG THANG ĐIỂM VÀ ÁNH XẠ MỨC DỊCH VỤ HCM (LOS)

Để trực quan hóa trên WebGIS, điểm số tổng hợp $S$ được tính:
$$S = S_{\text{speed}} (0 - 50) + S_{\text{stopped}} (0 - 30) + S_{\text{density}} (0 - 20)$$

Thang đo được phân định tương thích với **Highway Capacity Manual (HCM 2010 - Chapter 16: Urban Streets)**:

| Mức dịch vụ HCM (LOS) | Vận tốc / Vận tốc tự do ($V / V_f$) | Trạng thái hiển thị | Ngưỡng điểm số ($S$) | Ý nghĩa giao thông |
| :---: | :---: | :---: | :---: | :--- |
| **LOS A, B, C** | $> 50\% - 65\%$ | **`FREE` (Xanh)** | **$0 \le S < 35$** | Dòng tự do, vận tốc cao, xe máy di chuyển thông suốt |
| **LOS D** | $35\% - 50\%$ | **`SLOW` (Vàng)** | **$35 \le S < 65$** | Dòng ổn định nhưng bị chậm do mật độ tăng |
| **LOS E, F** | $< 35\%$ | **`CONGESTED` (Đỏ)** | **$65 \le S \le 100$** | Dòng bão hòa / tắc nghẽn nghiêm trọng, xe dừng dồn ứ |

---

## 5. TÀI LIỆU THAM KHẢO CHÍNH THỨC (REFERENCES)

1. **Bộ Khoa học và Công nghệ (2005)**, *Tiêu chuẩn Quốc gia TCVN 4054:2005: Đường ô tô — Yêu cầu thiết kế*, Nhà xuất bản Xây dựng, Hà Nội.
2. **Transportation Research Board (TRB) (2010)**, *Highway Capacity Manual (HCM 2010)*, National Research Council, Washington, D.C.
3. **Saaty, T. L. (1980)**, *The Analytic Hierarchy Process: Planning, Priority Setting, Resource Allocation*, McGraw-Hill, New York.
4. **Vũ Anh Tuấn, Phạm Xuân Mai (2021)**, "Nghiên cứu đặc trưng dòng giao thông hỗn hợp và giải pháp tổ chức giao thông đô thị tại TP. Hồ Chí Minh", *Tạp chí Giao thông Vận tải*, số 11, tr. 45-52.
5. **Dubská, M., Herout, A., Juránek, R., & Sochor, J. (2015)**, "Fully Automatic Camera Calibration for Traffic Surveillance", *IEEE Transactions on Pattern Analysis and Machine Intelligence (T-PAMI)*, 37(2), 387-400.

