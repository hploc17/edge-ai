# TRAFFIC CLASSIFIER V4 — FUZZY LOGIC 2021 FEASIBILITY

**Nghiên cứu nền:** Trinh Dinh Toan (2021), *Fuzzy-based Quantification of Congestion for Traffic Control*, Transport and Communications Science Journal, 72(1), pp. 1-8, DOI: 10.47869/tcsj.72.1.1.  
**Phạm vi:** Đánh giá tính khả thi; không thay đổi mã nguồn.

## Quy ước dẫn chứng

- `[PAPER]`: trực tiếp từ PDF bài báo.
- `[CODE]`: xác minh từ mã nguồn repository.
- `[INFERENCE]`: suy luận kỹ thuật.
- `[PROPOSED]`: đề xuất của dự án.
- `[UNVERIFIED]`: chưa xác minh, không được suy đoán thành tham số nghiên cứu gốc.

---

# 1. Executive Summary

## Kết luận: CONDITIONAL GO

Fuzzy Logic 2021 có thể được xem là baseline học thuật cho mức độ ùn tắc liên tục trên thang 0-1, nhưng **không thể tái hiện chính xác 100% mô hình nguyên bản** ở trạng thái hiện tại.

### Những kết luận chắc chắn

- `[PAPER]` Có hai đầu vào: speed và density; đầu ra congestion level nằm trong `[0, 1]`; AND dùng phép `MIN`.
- `[PAPER]` Table 1 chứa 19 luật kích hoạt và 6 tổ hợp không có luật.
- `[PAPER]` Bài báo công bố thực nghiệm trên một đoạn Pan-Island Expressway (Singapore), dùng field data và space mean speed.
- `[PAPER]` Không công bố Accuracy, Precision, Recall, F1 hoặc ground truth độc lập về tình trạng ùn tắc.
- `[PAPER]` Không nêu rõ hình dạng và tọa độ số đủ để tái lập chính xác mọi hàm thành viên đầu vào.
- `[PAPER]` Không nêu rõ bằng văn bản phép aggregation và defuzzification.
- `[CODE]` Project có vận tốc track qua Homography, PCE density, stopped ratio và telemetry 1 Hz.
- `[CODE]` Không tìm thấy Vmax, Kjam hoặc module Fuzzy V4 trong implementation hiện tại.

### Khuyến nghị

1. Không triển khai Fuzzy-A như mô hình exact reproduction.
2. `Fuzzy-B` là phương án baseline có kiểm soát nhất, sau khi công bố và kiểm chứng `Vmax`, `Kjam`, unit và cửa sổ thống kê.
3. `Fuzzy-C` chỉ là urban extension; không được gọi là mô hình nguyên bản hoặc giả định nó vượt trội.
4. Chỉ chạy shadow mode trước; giữ V1/V2/V3 để rollback.
5. Cần dữ liệu gán nhãn độc lập để chứng minh khả năng phân loại. Không có dữ liệu nhãn thì chỉ đánh giá tính toán, edge cases và độ ổn định.

---

# 2. Paper Reproducibility Audit

| Thành phần | Nguồn trong PDF | Trích xuất được | Cần giả định |
|---|---|---|---|
| Speed input | Sec. 1.2, Eq. (1), Fig. 1(a) | Có tên biến, đơn vị km/h trong Sec. 3 | Có cách xác định và hiệu chuẩn $V_{\max}$ |
| Density input | Sec. 1.2, Eq. (2), Fig. 1(b) | Có tên biến, veh/lane/km | Có cách xác định và hiệu chuẩn $K_{\text{jam}}$ |
| 5 mức Speed | Sec. 2.1, Eq. (1), Fig. 1(a) | VeryLow, Low, Medium, High, VeryHigh | Có tọa độ hàm thành viên |
| 5 mức Density | Sec. 2.1, Eq. (2), Fig. 1(b) | VeryLow, Low, Medium, High, VeryHigh | Có tọa độ hàm thành viên |
| 5 mức đầu ra | Sec. 2.1, Eq. (3), Fig. 2 | FreeFlow, Light, Moderate, Heavy, VeryHeavy | Không suy ra defuzz từ tâm hình |
| Hàm đầu ra | Fig. 2 | Tọa độ hình học 0.1, 0.3, 0.5, 0.7, 0.9 được quan sát | Cần xác nhận exact shape từ PDF |
| Hàm đầu vào | Fig. 1 | Có dạng họ đường cong/trượt định tính | Không thể rút ra coordinates chính xác |
| AND | Sec. 2.2 | MIN | Không |
| 19 luật | Table 1 | 19 ô có luật | Không |
| 6 ô khuyết | Sec. 2.2 | 6 tổ hợp | Có quy tắc project ngoài mô hình gốc |
| Aggregation | Không nêu bằng text | CHƯA XÁC MINH | Có |
| Defuzzification | Không nêu bằng text | CHƯA XÁC MINH | Có |
| Eq. (5) | Sec. 3, trang 5 | $\bar U_s \approx 1.026\bar U_t-1.89$ với time mean <70 km/h | Cần xác minh trực tiếp công thức và giới hạn |
| Eq. (6) | Sec. 3, trang 6 | $K=V/\bar U_s$ | Có zero-speed guard |
| Dữ liệu thực nghiệm | Sec. 3 và Acknowledgement | PIE Singapore, do LTA cung cấp | Không biết segment, duration đầy đủ, frequency |
| Accuracy/ground truth | Toàn bài | Không có | Không được suy đoán |

---

# 3. Mathematical Specification

## 3.1 Công thức nguyên bản

`[PAPER]`

Tập đầu vào:

$$
V=\{\text{VeryLow},\text{Low},\text{Medium},\text{High},\text{VeryHigh}\}
$$

$$
K=\{\text{VeryLow},\text{Low},\text{Medium},\text{High},\text{VeryHigh}\}
$$

Tập đầu ra:

$$
CL=\{\text{FreeFlow},\text{Light},\text{Moderate},\text{Heavy},\text{VeryHeavy}\}
$$

Dạng luật:

$$
\text{If }V\text{ is }V_i\text{ AND }K\text{ is }K_j
\text{ then }CL\text{ is }CL_k
$$

AND:

$$
\alpha_{ij}=\min(\mu_{V_i}(v),\mu_{K_j}(k))
$$

Miền đầu ra:

$$
CL^*\in[0,1]
$$

Trong Sec. 3:

$$
\bar U_s\approx1.026\bar U_t-1.89
$$

cho time mean speed dưới 70 km/h; với trên 70 km/h, bài báo nói ước lượng space mean speed bằng 98% time mean speed. Bài báo không công bố time/segment exact values đủ để xác nhận biểu đồ.

$$
K=\frac{V}{\bar U_s}
$$

## 3.2 Hàm thành viên đầu ra

`[PAPER, Fig. 2]` hình minh họa:

| Tập | Peak/support quan sát |
|---|---|
| FreeFlow | vai trái, 0 đến peak khoảng 0.1, giảm tới 0.3 |
| Light | tam giác, peak 0.3 |
| Moderate | tam giác, peak 0.5 |
| Heavy | tam giác, peak 0.7 |
| VeryHeavy | vai phải, tăng từ 0.7 đến 0.9, giữ 1 đến 1 |

Các tâm quan sát là 0.1, 0.3, 0.5, 0.7, 0.9. Điều này không chứng minh đỉnh và support của mọi hàm đầu vào.

## 3.3 Hàm thành viên đầu vào

`[PAPER, Fig. 1]` hai trục chuẩn hóa:

- Speed: $V/V_{\max}$.
- Density: $K/K_{\text{jam}}$.

Hình cho thấy 5 tập, nhưng không công bố điểm gãy số của từng tập. Không có giá trị số cụ thể cho $V_{\max}$ và $K_{\text{jam}}$, dù trục Surface Viewer có thể gợi ý miền 100-150 ở hình minh họa. Những gợi ý thị giác không được coi là tham số nghiên cứu gốc.

**CHƯA XÁC MINH:** shape Gaussian/sigmoid/tam giác, phương trình (1)-(2), tọa độ breakpoints.

## 3.4 Ma trận luật 5×5

| Speed \ Density | VeryLow | Low | Medium | High | VeryHigh |
|---|---|---|---|---|---|
| **VeryLow** | --- | --- | Heavy | VeryHeavy | VeryHeavy |
| **Low** | --- | Moderate | Moderate | Heavy | VeryHeavy |
| **Medium** | Light | Light | Moderate | Heavy | Heavy |
| **High** | FreeFlow | Light | Moderate | Moderate | --- |
| **VeryHigh** | FreeFlow | FreeFlow | Light | --- | --- |

Có 19 ô kích hoạt.

Sáu tổ hợp thiếu:

1. VeryLow speed - VeryLow density
2. VeryLow speed - Low density
3. Low speed - VeryLow density
4. High speed - VeryHigh density
5. VeryHigh speed - High density
6. VeryHigh speed - VeryHigh density

## 3.5 Aggregate và defuzzify

- AND: `[PAPER]` MIN.
- Tổng hợp luật: `[UNVERIFIED]`.
- Cách giải mờ: `[UNVERIFIED]`.
- Không được mặc định Mamdani-Centroid chỉ vì đây là cấu hình Fuzzy phổ biến.
- Bài báo không mô tả điều kiện no-rule; không có giá trị fallback gốc.

---

# 4. Repository Evidence Map

| Module | Bằng chứng | Kết quả |
|---|---|---|
| [speed_estimator.py](D:/Project/Project/analytics/speed_estimator.py:35) | `_bbox_bottom_center` | Dùng bbox bottom-center |
| [speed_estimator.py](D:/Project/Project/analytics/speed_estimator.py:49) | Homography $3\times3$ | Ánh xạ pixel sang mặt phẳng mét |
| [speed_estimator.py](D:/Project/Project/analytics/speed_estimator.py:277) | 2 s history, 0.8 s minimum, alpha 0.25, limit 130 km/h | Cấu hình ước lượng vận tốc thực tế |
| [speed_estimator.py](D:/Project/Project/analytics/speed_estimator.py:426) | mean/median theo track | Project có cả mean và median |
| [presence_counter.py](D:/Project/Project/analytics/presence_counter.py:13) | Confirmed/exit/lost track | Count xe theo Track ID trong ROI |
| [traffic_classifier.py](D:/Project/Project/analytics/traffic_classifier.py:444) | Filter speed theo `current_track_ids` | Tốc độ trong ROI |
| [traffic_classifier.py](D:/Project/Project/analytics/traffic_classifier.py:497) | $N/(road\ length\times lane)$ | Direct density veh/km/lane |
| [traffic_classifier.py](D:/Project/Project/analytics/traffic_classifier.py:506) | PCE weight theo class | PCE density PCU/km/lane |
| [roi_manager.py](D:/Project/Project/spatial/roi_manager.py:10) | road length, width, lane, points | Geometry config |
| [roi_traffic_nano.json](D:/Project/Project/configs/roi_traffic_nano.json:1) | 50 m, 7 m, 2 lane | Giá trị cấu hình hiện tại |
| [main.py](D:/Project/Project/main.py:453) | `--algo-version v1/v2/v3` | Chưa có V4 engine |
| [main.py](D:/Project/Project/main.py:1026) | publish 1 Hz | Telemetry window theo 1 giây |
| [mqtt_client.py](D:/Project/Project/communication/mqtt_client.py:94) | TELEMETRY_INTERVAL_S=1.0 | Đúng chu kỳ telemetry |

---

# 5. Input Compatibility Assessment

## 5.1 Vận tốc

- `[CODE]` Tọa độ bottom-center được chiếu bằng Homography; tốc độ tính bằng linear regression trên 2 giây.
- `[CODE]` `avg_speed_kmh` là mean; `median_speed_kmh` là median của các speed track trong ROI.
- `[CODE]` 0 km/h được ghi cho track đứng yên; `has_moved` phân biệt xe chưa từng di chuyển.
- `[INFERENCE]` Median speed track không được gọi là Space Mean Speed.
- `[PAPER]` Bài gốc đánh giá bằng Space Mean Speed được chuyển đổi từ time mean speed hoặc flow data.
- Do đó, dùng median speed là một quan sát project; phải đo lường riêng và không tuyên bố tương đương 100%.

Spot speed, time mean speed, space mean speed và running speed phải được tách rõ trong báo cáo kỹ thuật. Project không triển khai tất cả chung một đại lượng.

## 5.2 Mật độ

- Direct presence density: số track confirmed trong ROI chia chiều dài và số làn.
- PCE density: tổng PCE đang confirmed chia chiều dài và số làn.
- Derived density: $V/\bar U_s$ theo bài báo.

Ba đại lượng không đồng nhất.

- `PCE density` phụ thuộc class weight. Hệ số trong code lấy từ comment TCVN 4054:2005 nhưng source trong repository không đủ để xác minh ngoài tài liệu.
- `$V/\bar U_s$` có speed 0: không chia, cần guard hoặc density trực tiếp.
- Track ID switch có thể làm count/mật độ rơi biên; ROI loss và occlusion cần validation.

## 5.3 ROI

ROI hiện tại dài 50 m, rộng 7 m, 2 lane trong JSON. File không chứng minh nó cách giao lộ, quan sát toàn mặt đường hay không có đa luồng rẽ. Những nhận định này cần survey.

---

# 6. Domain Shift Assessment

Nghiên cứu gốc [PAPER] trên Pan-Island Expressway Singapore là uninterrupted-flow expressway. Hệ thống project triển khai trong bối cảnh đô thị Việt Nam có thể có:

- xe máy và ô tô hỗn hợp;
- đèn tín hiệu;
- stop-and-go;
- hàng đợi kéo dài;
- xe rẽ;
- mật độ PCE cao;
- low speed + low density;
- occlusion và track switch.

Các giả định phù hợp:

- hai biến speed/density mang thông tin;
- kết quả liên tục 0-1 có ý nghĩa;
- 19 luật phản ánh xu hướng chung high density/low speed.

Các giả định cần kiểm chứng lại:

- $V_{\max}$;
- $K_{\text{jam}}$;
- speed mean/median;
- density unit;
- 6 missing combinations;
- expected behavior tại đèn đỏ.

Không được thay $V_{\max}=30$ hoặc $K_{\text{jam}}$ bằng giá trị tùy ý.

---

# 7. Missing-Rule Risk Analysis

Bài báo deliberately loại 6 tổ hợp từ Table 1. Nếu đầu vào rơi tổ hợp không có luật:

- Không có firing strength;
- Không có output consequence;
- Không được gọi output là `UNKNOWN` hoặc `FREE`/`CONGESTED` từ mô hình gốc;
- Nếu ứng dụng CENTROID mà không guard, tổng mẫu số có thể bằng 0.

Các tình huống cần xử lý ở project:

| Tình huống | Xử lý gốc | Quy tắc project đề xuất |
|---|---|---|
| ROI không xe | Không mô tả | EMPTY; không suy congestion |
| Xe nhưng no valid speed | Không mô tả | INSUFFICIENT_DATA |
| All stopped | Paper không mô tả direct | Direct density and speed zero cần guard |
| V>Kjam | Không mô tả | CLAMP/OUT_OF_RANGE, không tự calibrate |
| Vmax/Kjam missing hoặc zero | Không mô tả | CONFIG_REQUIRED; không tính |
| NaN/Infinity | Không mô tả | INVALID_INPUT |
| No rule fired | No rule/output | NO_RULE_FIRED/UNKNOWN |
| Đèn đỏ normal | Không mô tả | 5 mức gốc không đủ context |
| Hàng đợi kéo dài | Không mô tả | Cần dwell/stopped context |
| Track ID switch | Không mô tả | Data quality warning |
| Missing frame | Không mô tả | thiếu metadata/data quality |

Mọi fallback là `PROJECT EXTENSION`, không phải quy tắc tác giả.

---

# 8. Fuzzy-A/B/C Comparison

| Tiêu chí | Fuzzy-A Original Paper | Fuzzy-B Calibrated | Fuzzy-C Urban Extension |
|---|---|---|---|
| Sát nghiên cứu gốc | Cao nhất về cấu trúc; thiếu exact params | Cao, giữ luật và hiệu chuẩn | Thấp hơn |
| Cần train | Không | Không | Không bắt buộc |
| Cần hiệu chuẩn | Có, nhưng không đủ basis trong paper | Có bắt buộc | Có và nhiều tham số hơn |
| Có luật mới | Không | Không trong bước đầu | Có thể |
| Dữ liệu Jetson | Một phần, missing-rule risk | Tương thích nếu unit rõ | Cần thêm data đèn/dwell |
| Phù hợp giao lộ | Thấp-trung bình | Trung bình | Tiềm năng cao; chưa chứng minh |
| Khả năng tái hiện | Thấp do paper gaps | Trung bình sau calibration | Thấp theo nghĩa reproduction |
| Khả năng kiểm chứng | Thấp nếu không ground truth | Tốt hơn qua field study | Cần validation mạnh |
| Rủi ro học thuật | Cao nếu claim exact | Trung bình nếu public calibration | Cao nếu không phân biệt extension |
| Rủi ro kỹ thuật | Cao ở biên/no-rule | Trung bình | Cao do thêm giả thuyết |

**Kết luận:** Fuzzy-B được xem là baseline chạy được sau khi có calibration protocol. Không mặc định Fuzzy-C tốt hơn.

---

# 9. Implementation Feasibility

## 9.1 Jetson

- `[CODE]` Project tương thích Python 3.6 ở các module; `main.py` ghi Python 3.6.
- `[CODE]` NumPy được import và sử dụng.
- Không cần scikit-fuzzy.
- Fuzzy 2-D có thể tự triển khai bằng Python thuần/NumPy.
- Telemetry 1 Hz cho phép tính ngoài GStreamer frame loop.
- Không cần thay JetPack/CUDA/TensorRT/DeepStream.
- Không có benchmark Jetson xác nhận CPU/RAM/latency trong task này; mọi con số hiện tại phải là `[UNVERIFIED]`.
- Docker: không phát sinh dependency nặng do fuzzy; vẫn cần quản lý numPy/Python compatibility.

## 9.2 Kiến trúc đề xuất

- V4 là module độc lập.
- Feature flag bật/tắt.
- Đầu vào:
  - median hoặc representative speed;
  - density hiện phân loại rõ là direct/PCE/derived;
  - count/valid-speed count;
  - geometry/version;
  - data_quality.
- Đầu ra:
  - `congestion_level`
  - `fuzzy_level`
  - `traffic_state`
  - `data_quality`
  - `method`
  - `reason`
- Shadow mode ghi đối chứng trước khi làm phương pháp chính.
- Rollback về V1/V2/V3.

---

# 10. Experimental Validation Plan

## 10.1 Kiểm chứng phép đo

- Sai số vận tốc bằng marker distance/GPS/ground-truth speed.
- Sai số mật độ bằng manual count và PCE independent.
- Sai số đếm bằng frame-by-frame count.
- Ảnh hưởng track switch/occlusion/ID loss.
- Ảnh hưởng Homography và road length.
- Sai lệch timestamp và replay FPS.

## 10.2 Kiểm chứng mô hình

Nếu có independent ground truth:

- Accuracy
- Macro-F1
- Precision
- Recall
- Confusion Matrix
- Recall CONGESTED
- False Alarm Rate

Nếu không có ground truth:

- correctness of equations;
- rule plausibility;
- deterministic edge cases;
- stability over time;
- calibration sensitivity;
- không gọi kết quả là classification accuracy.

## 10.3 Hiệu chuẩn

Chạy sensitivity cho:

- $V_{\max}$;
- $K_{\text{jam}}$;
- speed definition;
- density definition;
- input noise;
- missing frames;
- missing rules;
- road length/lane count.

Hiệu chuẩn theo từng tuyến phải công bố phương pháp, dataset, split và independent validation.

## 10.4 Không so sánh sai

Không lấy Figure 5 của bài báo để khẳng định Accuracy cao hơn V1/V2/V3. Không công bố kết quả Accuracy nếu không cùng ground truth, data split và protocol.

---

# 11. Impact by Project Component

| Thành phần | Đánh giá |
|---|---|
| YOLO11/DeepStream/nvtracker | CÓ THỂ HOÃN: V4 không cần thay, nhưng cần nghiên cứu tracking quality |
| Speed estimator | BẮT BUỘC phân biệt và kiểm chứng speed measure |
| ROI/Homography | BẮT BUỘC survey geometry/calibration |
| Presence counter | BẮT BUỘC xác nhận density/count quality |
| Traffic analyics | BẮT BUỘC thêm method/data_quality độc lập |
| MQTT | NÊN LÀM: additive fields, không phá schema |
| FastAPI/Database | NÊN LÀM: lưu model version và calibration |
| WebGIS | NÊN LÀM: giữ 5-level source và 3-level display |
| V1/V2/V3 | KHÔNG CẦN thay; giữ rollback |

---

# 12. Mapping 5 Levels to 3 States

Gốc có 5 mức:

- FreeFlow
- Light
- Moderate
- Heavy
- VeryHeavy

WebGIS có 3 mức:

- FREE
- SLOW
- CONGESTED

Mapping đề xuất để xem xét:

- FreeFlow, Light -> FREE
- Moderate -> SLOW
- Heavy, VeryHeavy -> CONGESTED

Đây là **PROJECT MAPPING**, không phải quy định trong bài báo. Không dùng ngưỡng 0.35/0.65 của Traffic Score cũ cho Congestion Level. Nếu cần ngưỡng rời rạc cho UI, phải có ground-truth test riêng.

---

# 13. Academic Defense Risks

Hơn 15 câu hỏi cần trả lời:

1. **Vì sao lại chọn Fuzzy?** Có explainability và không train classifier.
2. **Bài báo nêu exact membership không?** Không đủ số, cần calibration/assumption.
3. **$V_{\max}$ lấy từ đâu?** Chưa xác minh; không tự gán.
4. **$K_{\text{jam}}$ lấy từ đâu?** Chưa xác minh; cần field calibration.
5. **AND dùng phép nào?** MIN theo paper.
6. **Defuzzification là gì?** Chưa xác minh trong text bài báo.
7. **Dùng Mamdani-Centroid có phải paper không?** Không thể khẳng định exact; đó là giả định triển khai nếu chọn.
8. **Có 19 hay 25 luật?** 19 luật kích hoạt, 6 tổ hợp khuyết.
9. **No-rule xử lý thế nào?** UNKNOWN/NO_RULE_FIRED; không tự coi là FREE/CONGESTED.
10. **Speed project là space mean speed không?** Không đủ cơ sở; median/track speed khác.
11. **PCE density là density bài báo không?** Không.
12. **Speed zero làm density flow/speed thế nào?** Không chia; dùng direct density hoặc guard.
13. **Bài báo có Accuracy không?** Không.
14. **Có ground truth không?** Không công bố.
15. **PIE Singapore có giống Việt Nam không?** Không; domain shift rõ.
16. **Xe máy ảnh hưởng thế nào?** PCE và density behavior cần đo.
17. **Dừng đèn đỏ xử lý thế nào?** Fuzzy gốc chưa có; chỉ có Fuzzy-C/context extension.
18. **Fuzzy-C đã được chứng minh tốt hơn không?** Chưa.
19. **Calibration theo camera có cần dữ liệu không?** Có, có ground truth/reference.
20. **Có benchmark Jetson không?** Chưa có trong task; không tự tạo số liệu.

---

# 14. Final Recommendation

- **Tái hiện nguyên bản:** chỉ có thể làm baseline có ghi chú thiếu tham số; không gọi exact 100%.
- **Hiệu chuẩn:** cần $V_{\max}$, $K_{\text{jam}}$, unit, window và no-rule guard.
- **Bổ sung luật đô thị:** không trong baseline; chỉ làm `PROJECT EXTENSION` sau validation.
- **Dữ liệu gán nhãn:** bắt buộc để chứng minh Accuracy/Recall/False Alarm.
- **Triển khai trước bảo vệ:** kỹ thuật khả thi, nhưng acceptance học thuật phụ thuộc field data và ground truth.

---

# 15. Implementation Roadmap

1. Giữ V1/V2/V3 nguyên trạng.
2. Tạo Fuzzy module dưới feature flag.
3. Công khai model assumptions và missing rules.
4. Thêm `data_quality` cho empty/invalid/no-rule.
5. Shadow mode 1 Hz đối chứng.
6. Survey ROI, Homography, road length/lane.
7. Thu video và independent labels.
8. Hiệu chuẩn $V_{\max}$/$K_{\text{jam}}$ theo tuyến.
9. Chạy sensitivity và confusion metrics.
10. Chỉ bật Fuzzy làm output chính sau khi có kết quả field validation.
