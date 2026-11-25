# TRAFFIC V4 — HYBRID FUZZY–QUEUE FEASIBILITY

**Phạm vi:** đánh giá tài liệu, dữ liệu video và khả năng tích hợp; không triển khai mã nguồn.

Các nhãn:

- `[PAPER]`: trực tiếp từ bài báo.
- `[STANDARD]`: tiêu chuẩn hoặc tài liệu chính thức.
- `[CODE]`: xác minh trong repository.
- `[PROPOSED]`: đề xuất của dự án.
- `[INFERENCE]`: suy luận kỹ thuật.
- `[UNVERIFIED]`: chưa truy cập/xác minh được.

---

# 1. Executive Summary

## Kết luận theo phương án

| Phương án | Kết luận | Lý do |
|---|---|---|
| A — Calibrated Fuzzy Baseline | **CONDITIONAL GO** | Có nguồn 2021; có thể dùng Mamdani/MIN/MAX/Centroid từ Erdinç 2023 như phương án tích hợp, nhưng Vmax/Kjam và defuzz của 2021 vẫn thiếu số liệu. |
| B — Fuzzy + Queue Observation | **CONDITIONAL GO** | Có stopped/dwell count và ROI, nhưng chưa chứng minh đo được queue length/queue clearance. Chỉ nên xuất hai kết quả độc lập. |
| C — Full Fuzzy–Queue–Signal | **NO-GO tại thời điểm hiện tại** | Không xác minh được tín hiệu điều khiển ROI, chu kỳ đèn, queue clearance và cycle failure qua dữ liệu hiện có. |

Đề xuất ban đầu: **OPTION B** là phương án có thể thực hiện có kiểm soát nhất, không gộp bằng trọng số tự đặt. Tuy nhiên, kết quả chỉ được công bố là:

1. Fuzzy congestion assessment.
2. Queue/stopped evidence quan sát được.

Việc gộp thành một traffic state cuối cùng phải là một nghiên cứu mới có ground truth.

---

# 2. Literature Evidence Matrix

| Tài liệu | Đặc trưng được xác minh | Công thức/luật | Giới hạn |
|---|---|---|---|
| Trinh Dinh Toan 2021 | 2 input speed/density, 5 output levels, 19 rules | MIN AND, 5×5 rule matrix, CL∈[0,1] | Thiếu membership breakpoints; không rõ aggregation/defuzz; thiếu Vmax/Kjam số; không có Accuracy |
| Trinh Dinh Toan 2022 | Stage 1: CL, Congestion Mobility, Congestion Status; Stage 2 predicted trend; queue length block | Piece-wise linear; Mamdani; centroid được nêu ở stage surfaces | Expressway incident/ramp control; stage 2 dùng SVM forecast và risk factors; không phải signalized urban queue-clearance method |
| Erdinç et al. 2023 | Mamdani two-stage; flow/density predicts next speed; DATEX II speed bands | $f=v k$; MIN AND; MAX aggregation; centroid | Motorway Italy, 15-min detector data, not camera-tracking; no queue/signal; no classification Accuracy in full text |
| FHWA/TSD | Official source for signal timing and queue concepts | Official page redirects to Signal Timing Manual, second edition | PDF/full old manual không truy cập được trong phiên làm việc; chưa có công thức queue residual/cycle failure trích xuất |
| LTRC 2026 FR-724 | Improved signalized intersection performance using CV/AI | URL/report supplied | PDF bị 403 trong môi trường; chưa xác minh model, queue formula, signal detection hoặc kết quả |

Nguồn chính:

- 2021: https://doi.org/10.47869/tcsj.72.1.1
- 2022: https://doi.org/10.47869/tcsj.73.4.4
- 2023: https://doi.org/10.3390/futuretransp3030047
- FHWA: https://ops.fhwa.dot.gov/publications/fhwahop08024/
- LTRC: https://www.ltrc.la.gov/pdf/2026/FR_724.pdf

---

# 3. Fuzzy 2021 Gap Resolution

## Đã được tài liệu khác hỗ trợ

`[PAPER]`/`[PAPER]`:

- 2021 xác nhận 19 luật và AND MIN.
- 2022 xác nhận lại CL rule matrix và dùng centroid trên fuzzy surfaces.
- 2022 có queue length, congestion mobility và congestion status, nhưng là expressway incident context.

`[PAPER]` Erdinç 2023:

- Xác nhận Mamdani.
- Xác nhận triangular membership trong một implementation cụ thể.
- Xác nhận AND bằng MIN.
- Xác nhận MAX aggregation.
- Xác nhận centroid defuzzification.

Đây là bằng chứng cho 2023, không phải bằng chứng rằng Toan 2021 cũng dùng Centroid.

## Khoảng trống còn tồn tại

- 2021 không công bố exact membership breakpoints cho speed/density.
- Không có giá trị số cho Vmax/Kjam.
- Không nêu aggregation/defuzzification bằng text.
- Không có ground truth hoặc Accuracy.
- 2022 không cung cấp PCE density, ROI queue length hoặc signal phase cho urban camera.
- 2023 dùng 15-minute motorway sensor data, không phải YOLO/nvtracker.
- LTRC 2026 không thể kiểm chứng full text trong phiên này.

---

# 4. Video Dataset Audit

Repository có 20 file video trong `Video/`: 18 file raw H264 + 2 file MP4. Một cặp H264 có SHA256 trùng khớp:

- `18.h264`
- `Screen_Recording_20261107_100821.h264`

Do đó có **20 file, 19 nội dung duy nhất**. Tên/size không được dùng làm ground truth.

## Metadata

| File | Thời lượng | FPS | Resolution | Codec/ghi chú |
|---|---:|---:|---|---|
| 2.h264 | 31.20 s | 25 nominal | 1920×1080 | H264 raw; metadata frame count usable with 25 FPS |
| 3.h264 | 20.64 s | 25 nominal | 3840×2160 | H264 raw |
| 4.h264 | 30.20 s | 25 nominal | 1920×1080 | H264 raw |
| 5.h264 | 24.96 s | 25 nominal | 1920×1080 | H264 raw |
| 6.h264 | 32.44 s | 25 nominal | 2560×1440 | H264 raw |
| 7.h264 | 18.48 s | 25 nominal | 3840×2160 | H264 raw |
| 8.h264 | 70.12 s | 25 nominal | 3840×2160 | H264 raw |
| 9.h264 | 46.56 s | 25 nominal | 3840×2160 | H264 raw |
| 10.h264 | 11.52 s | 25 nominal | 3840×2160 | H264 raw |
| 11.h264 | 61.68 s | 25 nominal | 1280×720 | H264 raw |
| 12.h264 | 72.56 s | 25 nominal | 888×496 | H264 raw |
| 13.h264 | 65.88 s | 25 nominal | 1280×720 | H264 raw |
| 14.h264 | 23.16 s | 25 nominal | 1280×720 | H264 raw |
| 15.h264 | 71.24 s | 25 nominal | 1920×1080 | H264 raw |
| 16.h264 | 40.84 s | 25 nominal | 3840×2160 | H264 raw |
| 17.h264 | 6.76 s | 25 nominal | 3840×2160 | H264 raw |
| 18.h264 | 428.24 s | 25 nominal | 1920×1080 | H264 raw |
| Screen_Recording_20261107_100821.h264 | 428.24 s | 25 nominal | 1920×1080 | SHA256 trùng `18.h264` |
| 1107.mp4 | 161.93 s | 30.00 | 1920×1080 | MP4; representative frame là dashboard/screen recording |
| Screen_Recording_20261107_100821.mp4 | 356.87 s | 92.27 reported | 2400×1080 | MP4; FPS metadata bất thường/cần xác minh |

`[UNVERIFIED]` FPS thực tế của các file H264; 25 là FPS suy ra từ OpenCV, chưa có ffprobe xác nhận container. Screen MP4 92.27 FPS cần kiểm tra bằng player/ffprobe, không nên dùng làm ground truth.

## Quan sát trực tiếp frame đại diện

Mẫu kiểm tra: frame đầu, 25%, 50%, 75%, 99%.

- Nhiều clip traffic có xe máy, ô tô, crossing và stop line; một số frame có biển báo/đèn nhỏ nhưng không xác nhận đèn điều khiển luồng trong ROI.
- `18.h264`/bản trùng: có scene giao lộ, hàng xe dừng/di chuyển chậm, stop line và xe máy. Không thấy bằng chứng trọn chu kỳ đỏ-vàng-xanh trong mẫu 5 frame.
- `1107.mp4`: frame đại diện là dashboard, không phải clip giao thông nguyên gốc.
- `Screen_Recording_20261107_100821.mp4`: frame đại diện là màn hình ghi lại camera/WebGIS, không xác nhận được nội dung/phase.
- Các clip H264 còn lại chỉ có thể đánh giá qua representative frames; không có đủ bằng chứng về pha đèn hoặc cuối hàng chờ.

Không có tác giả ground truth, file nhãn, timestamp overlay hoặc metadata chu kỳ đèn trong repository. Vì vậy không công bố phần trăm video phù hợp.

---

# 5. Signal Visibility Assessment

Theo mẫu frame và strict review:

| Kết quả | Đánh giá |
|---|---|
| Thấy đèn tín hiệu rõ ràng, cùng hướng, đầy đủ 3 pha | **CHƯA XÁC MINH** |
| Xác định trọn chu kỳ | **CHƯA XÁC MINH** |
| Theo dõi nhiều chu kỳ | **CHƯA XÁC MINH** |
| Xác định stop line, vạch dừng | Có dấu hiệu ở một số scene, nhất là 18/screen duplicate |
| Pha đèn inferred từ xe dừng | Không công nhận là observed phase |

`INFERRED_SIGNAL_PHASE` chỉ được ghi trong log nếu suy từ xe dừng/đi. Không được dùng làm ground truth cycle.

---

# 6. ROI and Geometry Assessment

`[CODE]` `config/roi_traffic_nano.json` xác nhận 50 m road length, 7 m road width, 2 lane.

Phân biệt đại lượng:

- Stopped Vehicle Count: số track có speed dưới stopped threshold.
- Queue Vehicle Count: số xe thuộc hàng chờ đã xác định.
- Observed Queue Length: chiều dài đo được đến tail queue trong ROI.
- Estimated Queue Length: ước lượng dựa trên spacing/density.
- Residual Queue: xe còn lại sau pha xanh/kết thúc pha.
- Cycle Failure: bắt buộc phase/clearance evidence.

Hiện trạng:

- Có thể đo stopped vehicle count.
- Chưa chứng minh độ chính xác queue vehicle count.
- Không có bằng chứng toàn bộ tail queue thuộc ROI.
- Không có vạch dừng tham chiếu cho tất cả camera.
- Không thể công bố observed queue length hoặc residual queue.

---

# 7. Tracking and Queue Measurement Feasibility

`[CODE]`

- Track ID từ NvDCF.
- Presence counter confirm enter 0.10 s, exit 0.25 s.
- Lost timeout 1.0 s.
- Speed history 2 s, minimum 0.8 s.
- Stopped threshold mặc định 5 km/h.
- `_ignore_never_moved=True` loại xe chưa từng di chuyển khỏi một số thống kê.

Các độ tin cậy:

| Khả năng | Đánh giá |
|---|---|
| Xác định xe dừng theo speed | Khả thi có kiểm chứng |
| Theo xe qua đỏ/xanh | Chưa xác minh đủ |
| Phát hiện xe rời hàng | Có track ID nhưng cần ground truth |
| Đếm xe còn lại | Chưa đo được stable |
| Phân biệt rẽ/đi thẳng | Có direction field, chưa validate |
| ID switch | Không chứng minh xử lý hoàn toàn |
| Occlusion xe máy | Rủi ro cao |

Metric đề xuất:

$$
R_c=\frac{|S_{\text{start}}\cap S_{\text{end}}|}{|S_{\text{start}}|}
$$

Điều này là `[PROPOSED METRIC]`, không phải công thức FHWA.

Không dùng được nếu không xác định start/end green, tập xe xếp hàng và track continuity. Nếu mẫu số 0, trả `NOT_MEASURABLE`.

---

# 8. Mathematical Specification

## Fuzzy congestion A

`[PAPER]` Toan 2021:

$$
\alpha_r=\min(\mu_V(v),\mu_K(k))
$$

AND của luật được xác minh là MIN.

`[PAPER]` 2023 nghiên cứu riêng xác nhận implementation Mamdani:

$$
\mu_{agg}(y)=\max_r\left[\min(\alpha_r,\mu_{CL,r}(y))\right]
$$

$$
CL^*=\frac{\int y\mu_{agg}(y)dy}{\int\mu_{agg}(y)dy}
$$

Rời rạc:

$$
CL^*\approx\frac{\sum_m y_m\mu_{agg}(y_m)}
{\sum_m\mu_{agg}(y_m)}
$$

Nếu dùng công thức 2023 cho luật 2021, phải gọi:

**PROJECT ADAPTATION — not original 2021.**

## Không kích hoạt luật

Nếu:

$$
\sum_r\alpha_r=0
$$

hoặc aggregate toàn phần bằng 0:

$$
output=\text{UNKNOWN},\quad data\_quality=\text{NO\_RULE\_FIRED}
$$

Không auto FreeFlow/Congested.

## Queue evidence

Các đại lượng quan sát:

$$
stopped\_ratio=\frac{n_{\text{stopped moved tracks}}}{n_{\text{evaluated tracks}}}
$$

$$
queue\_count=n_{\text{confirmed stopped tracks in queue region}}
$$

$$
queue\_trend=
\text{EMA/slope/compare}_{\Delta t}(queue\_count)
$$

Các công thức queue trend là `[PROPOSED]`; slope/EMA không được cho là công thức FHWA.

---

# 9. Queue–Signal Integration

Không tìm đủ cơ sở để tổng hợp Fuzzy và queue bằng weighted score.

## A

Chỉ kết quả fuzzy.

## B

Hai trường độc lập:

- `congestion_level` Fuzzy.
- `queue_evidence` gồm stopped count, queue trend, data quality.

Không ánh xạ queue thành Congested trừ khi có ground truth.

## C

Mới đủ khi có:

- observed signal phase,
- green start/end,
- stopped queue start/end,
- queue clearance,
- residual queue,
- cycle failure.

Hiện không đủ bằng chứng. Không suy cycle failure từ stop speed đơn lẻ.

---

# 10. Architecture Comparison

| Tiêu chí | A | B | C |
|---|---|---|---|
| Nghiên cứu nền | Có 2021/2023 | Có 2021/2022; queue chưa xác minh | Có nhiều nguồn; tích hợp chưa biết |
| Công thức trích xuất | Một phần, calibration gap | Có, queue trend phải tự thiết kế | Chưa đủ |
| Cần train | Không | Không | Không bắt buộc, signal detector có thể tăng nhu cầu |
| Cần hiệu chuẩn | Vmax/Kjam | Vmax/Kjam và queue region | Nhiều tham số |
| Dữ liệu hiện đáp ứng | Speed/density/PCE có | Stopped count có; queue length chưa | Pha đèn/clearance chưa |
| Cần thấy đèn | Không | Không bắt buộc | Có |
| Cần theo hàng | Không | Có | Có |
| Phân biệt đèn đỏ | Không tự động | Gián tiếp bằng stopped/dwell | Có tiềm năng |
| Số module chỉnh sửa | Thấp | Trung bình | Cao |
| Rủi ro Jetson | Thấp | Thấp-trung bình | Chưa benchmark |
| Khả năng kiểm chứng | Trung bình | Trung bình-thấp nếu không GT | Thấp |
| Rủi ro hội đồng | Cao do ta giấy tham số thiếu | Trung bình nếu công khai hai output | Rất cao |

---

# 11. Jetson Nano Engineering Assessment

- `[CODE]` Python 3.6-compatible modules.
- `[CODE]` NumPy available in code.
- Fuzzy light inference có thể chạy 1 Hz.
- Không cần scikit-fuzzy.
- Không cần thay YOLO/DeepStream/nvtracker cho A/B.
- Queue tracking có thể thêm metadata 1 Hz.
- Signal detector không được thêm nếu chưa validate.
- Không benchmark Jetson trong task này: **NOT_BENCHMARKED**.
- Shadow mode: khả thi bằng config/telemetry field.
- Rollback: giữ V1/V2/V3.

---

# 12. Experimental Validation Design

## Ground truth cần thu thập

- manual free/slow/congested labels;
- vehicle count/density manual;
- speed reference;
- queue tail;
- green/red phase;
- green start/end;
- remaining queue at phase end;
- cycle failure.

## Metrics

- Accuracy
- Macro-F1
- Precision
- Recall
- Confusion matrix
- Recall CONGESTED
- false alarm at red light
- queue count MAE
- queue length MAE nếu có marker
- residual queue accuracy
- signal phase accuracy

Không lấy V1/V2/V3 labels làm ground truth.

## Ablation

1. Fuzzy only.
2. Fuzzy + stopped/queue trend.
3. Fuzzy + queue + verified signal.

Chỉ công bố improvement khi cùng clip và cùng ground truth.

---

# 13. Academic Validity

Điểm mạnh:

- Có nguồn peer-reviewed cho fuzzy, queue concept and Mamdani.
- Không train classifier.
- Có thể chạy nhẹ.

Hạn chế:

- Bài 2021 thiếu exact parameters.
- PCE density không tương đương density bài báo.
- 2022 là incident expressway, không phải signalized urban intersection.
- 2026 LTRC chưa truy cập được.
- FHWA PDF chưa truy cập được.
- video hiện không chứng minh đèn/queue clearance.
- không có Accuracy/Ground truth.

Rủi ro:

- claim exact reproduction;
- claim Centroid là 2021;
- claim Vmax/Kjam calibration;
- claim queue formula FHWA;
- claim cycle failure from speed;
- claim model superior without experiment.

---

# 14. Final Recommendation

## Chọn OPTION B

Lý do:

1. Fuzzy baseline có nguồn; 2023 hỗ trợ Mamdani implementation.
2. Project đã có stopped speed/dwell/track count.
3. Không yêu cầu detector đèn chưa chứng minh.
4. Có thể giữ hai outputs riêng: Fuzzy + Queue evidence.
5. Phù hợp Jetson 1 Hz.
6. Có rollout shadow mode/rollback.

Loại A:

- Không xử lý context đèn/hàng chờ.

Loại C:

- Không đủ visibility/ground truth; không implement signal detector.

---

# 15. Implementation Roadmap

1. Không sửa model cũ.
2. Thêm feature flag V4 shadow.
3. Triển khai A/B as independent telemetry outputs.
4. Hoàn thiện data_quality.
5. Ghi model version và ROI version.
6. Survey stop line, queue tail, lane directions.
7. Thu label independent.
8. Validate track/speed/density.
9. Cài queue observation region sau khi thấy đủ evidence.
10. Chỉ thử signal/clearance nếu quan sát được đèn và chu kỳ.
11. Chạy ablation A vs B.
12. Không kích hoạt C nếu chưa có ground truth.

---

# 16. Final Decision Table

| Điều kiện bắt buộc | Có | Không | Chưa xác minh | Bằng chứng |
|---|---|---|---|---|
| Speed hợp lệ | Có | | | Homography/TrackSpeedEstimator |
| Density hợp lệ | Có | | | PCE direct, direct density |
| Fuzzy có đặc tả kiểm soát | | | Có | 2021 19 rules, thiếu params/defuzz |
| ROI thấy vạch dừng | | | Có | Chỉ xác minh ở một số frame |
| Có thể quan sát hàng chờ | Có một phần | | | `18.h264`/frame representative |
| Có thể đo Queue Clearance | | | Chưa | Không có start/end green |
| Nhìn thấy pha đèn chính xác | | | Chưa | Không đủ frame/phase |
| Có video đủ chu kỳ | | | Chưa | Không xác minh trọn cycle |
| Tracking đủ ổn định | Có một phần | | | Cv/tracker, cần validation |
| Không train thêm classifier | Có | | | Cấu trúc V4 đề xuất |
| Có thể chạy Jetson | Có khả năng | | | Không benchmark |
| Có UNKNOWN và rollback | Có thiết kế | | | Dự kiến; chưa implement |
| Có dữ liệu kiểm chứng | Có video | | Ground truth chưa có | Không có label độc lập |
