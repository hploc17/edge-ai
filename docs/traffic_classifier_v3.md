# SPI v3 — hướng dẫn WebGIS và Jetson

Đây là phương pháp hỗ trợ giám sát dựa trên tốc độ ROI, không phải chứng nhận
hợp chuẩn hay kết luận pháp lý về ùn tắc. V1/V2 giữ lại để so sánh A/B.

## 1. Công thức và cách đọc

```text
v = median(v_1, ..., v_n)                 [km/h, track hợp lệ trong ROI]
SPI_raw = 100 × v / reference_speed_kmh
SPI = clamp(SPI_raw, 0, 100)
score = 100 − SPI
```

| SPI | Điểm giảm tốc | Nhãn tức thời |
|---|---|---|
| >75 | <25 | FREE — rất thông thoáng |
| >50 đến 75 | 25 đến <50 | FREE — thông thoáng |
| >25 đến 50 | 50 đến <75 | SLOW — chậm |
| ≤25 | ≥75 | CONGESTED — ùn tắc |

Ví dụ tốc độ giới hạn **40 km/h**: trung vị 30 → SPI75, điểm25, FREE;
trung vị20 → SPI50, điểm50, SLOW; trung vị10 → SPI25, điểm75, CONGESTED.
40 km/h chỉ là ví dụ, không phải mặc định. Điểm75 không phải xác suất kẹt75%.

`traffic_status` là nhãn đã xác nhận. V3 mặc định yêu cầu nhãn mới duy trì
10 giây, **không phải** bỏ phiếu đa số v1/v2. Trong lúc pending, điểm tức thời
và màu theo nhãn đã xác nhận có thể khác dải. Không ép điểm về dải của nhãn,
vì sẽ phá công thức phần bù.

## 2. Điều khiển từ WebGIS

Điều kiện: backend, frontend và mã Jetson cùng được cập nhật; Jetson agent
đang chạy, node được duyệt và kết nối MQTT. Cập nhật WebGIS không tự cập nhật
chương trình Jetson.

1. Mở **Quản lý thiết bị**, chọn Jetson, mở **Điều khiển từ xa**.
2. Chọn Camera CSI hoặc video trên Jetson và lấy ảnh preview.
3. Vẽ Detection ROI bao phủ vùng phát hiện. Theo kiểm tra phối cảnh hiện tại
   của giao diện, Analysis ROI có đúng bốn điểm: P1 gần-trái, P2 gần-phải,
   P3 xa-phải, P4 xa-trái; cạnh gần nằm phía dưới ảnh. Nếu góc camera không
   phù hợp giả thiết này, cần hiệu chuẩn/điều chỉnh bộ kiểm tra riêng, không
   nhập kích thước giả chỉ để vượt qua kiểm tra.
4. Nhập kích thước thực tế và số làn của **chính ROI**, không lấy chiều dài
   toàn tuyến GIS thay thế. Sai kích thước làm sai homography/tốc độ/mật độ.
5. Chọn **SPI v3**, nhập tốc độ tham chiếu theo biển báo áp dụng tại đoạn.
   Ghi nguồn và điều kiện áp dụng trong hồ sơ khảo sát.
6. Bắt đầu với tối thiểu **3 track**, xác nhận **10 giây**.
   Tốc độ dòng tự do là tùy chọn, chỉ nhập khi đo riêng; chưa đo thì để trống.
7. Lưu ROI và thuật toán; chờ **Jetson xác nhận lưu thành công**.
   HTTP “đã gửi” chưa chứng minh thiết bị đã lưu. Cấu hình giao thông được gửi
   cùng toàn bộ ROI qua endpoint hiện có, không phải cập nhật từng trường rời.
8. Dừng/chạy lại pipeline bằng cấu hình **remote** để áp dụng. Lưu thành công
   không đồng nghĩa worker đang chạy đã dùng cấu hình mới.
9. Kiểm tra telemetry mới trên bảng chi tiết: phiên bản v3, tốc độ tham chiếu,
   tốc độ đại diện, số track hợp lệ, SPI, điểm và trạng thái dữ liệu.

Khi đổi nguồn camera/video, kiểm tra lại ROI và hiệu chuẩn; không tái sử dụng
homography giữa các góc camera khác nhau. Nếu Jetson chưa nâng cấp mã, không
dùng ACK của agent cũ làm bằng chứng các trường v3 mới được áp dụng.

### Cấu hình gửi cùng ROI

```json
{
  "algorithm_version": "v3",
  "reference_speed_kmh": 40.0,
  "minimum_valid_tracks": 3,
  "status_confirm_seconds": 10.0,
  "free_flow_speed_kmh": null
}
```

Đây chỉ là phần giao thông; request đầy đủ vẫn cần ROI và kích thước.
Ngưỡng v3 cố định SPI50/25, tương ứng điểm50/75.
Không chỉnh ngưỡng để làm màu “đẹp hơn”. Tốc độ tham chiếu thiếu phải dẫn đến
CONFIG_REQUIRED, không tự lấy tốc độ thiết kế trong metadata GIS.

Thứ tự chọn phiên bản: tham số CLI `--algo-version` → cấu hình ROI đã chọn
→ biến môi trường `TRAFFIC_ALGORITHM_VERSION` → v2. Vì vậy lựa chọn từ WebGIS
không bị biến môi trường v2 cũ ghi đè; CLI tường minh vẫn có quyền ưu tiên.
Trường tham chiếu null trong cấu hình là yêu cầu xóa giá trị, không lấy lại
`SPI_REFERENCE_SPEED_KMH` từ môi trường.

## 3. Thiếu dữ liệu và xe dừng

| Dữ liệu | Diễn giải / xử lý |
|---|---|
| CONFIG_REQUIRED | Kiểm tra tốc độ tham chiếu và cấu hình thực sự đang chạy |
| EMPTY | Không có xe được xác nhận trong ROI, không phải phép đo SPI100 |
| INSUFFICIENT_DATA | Chưa đủ tốc độ hợp lệ; kiểm tra ROI, tracker, che khuất |
| INVALID_SPEED | Dữ liệu tốc độ không hợp lệ |
| VALID nhưng pending | Đủ dữ liệu đo, đang chờ xác nhận nhãn |
| STALE trên WebGIS | Telemetry quá cũ/mất kết nối, không suy ra thông thoáng |

Thiếu dữ liệu hiển thị --/UNKNOWN. Giá trị0 trong alias tương thích không được
đưa vào thống kê như điểm hợp lệ. Xe có tốc độ hợp lệ bằng0 vẫn được tính,
kể cả chưa từng di chuyển từ khi mở camera. Dùng ROI/vùng loại trừ tránh bãi
đỗ; không loại cả hàng xe chờ bằng cờ `has_moved=False`.

## 4. Input/output

Input: timestamp luồng video, track ID hiện diện, tốc độ km/h sau homography
và lọc, lớp xe, ROI, chiều dài, số làn, cấu hình v3.

| Trường output | Ý nghĩa |
|---|---|
| algorithm_version | Phiên bản thực sự phát telemetry |
| representative_speed_kmh | Trung vị dùng tính SPI |
| representative_speed_method | Phương pháp tổng hợp tốc độ |
| reference_speed_kmh | Mẫu số SPI |
| spi | Chỉ số giới hạn0–100, cao là thông thoáng |
| speed_ratio_percent | Tỷ lệ chưa giới hạn, có thể >100 |
| speed_reduction_index | Điểm100−SPI |
| congestion_score | Alias số nguyên, không suy lại nhãn từ số đã làm tròn |
| traffic_status | Nhãn đã xác nhận, nguồn chính cho màu |
| raw_traffic_status | Nhãn tức thời |
| score_thresholds | Ngưỡng điểm50/75 |
| valid_speed_tracks | Số track tốc độ hợp lệ |
| data_quality / reason | Chất lượng dữ liệu / lý do không kết luận |
| status_pending | Đang chờ chuyển nhãn |
| hcm_los_proxy | A–F tham khảo; null khi chưa có tốc độ dòng tự do |

Backend/frontend ưu tiên nhãn edge gửi. Không áp ngưỡng35/65 của v1/v2 cho v3.
Màu nhãn ổn định và điểm tức thời phải được giải thích riêng khi pending.

## 5. Mật độ, lưu lượng và LOS

```text
k_raw = N / (L_km × số_làn)                    [xe/km/làn]
k_pcu = Σ(N_loại × PCU_loại)/(L_km × số_làn)   [PCU/km/làn]
q_ước_lượng = k_raw × v_trung_bình × số_làn    [xe/giờ toàn đoạn]
```

Các đại lượng này không cộng vào điểm v3. Lưu lượng là ước lượng từ ROI,
không thay cho đếm xe qua mặt cắt. Không lấy mật độ PCU rồi gắn đơn vị xe/giờ.
ROI entry rate cũng khác phép đếm qua mặt cắt.

Hệ số v3: bicycle0,2; motorbike0,3; car1; truck2; bus2,5.
Truck/bus không tách số trục/số chỗ nên là phép ánh xạ của dự án, cần ghi giới hạn.
Vehicle_fire là cảnh báo sự cố, không phải loại xe vật lý.
V1/V2 giữ hệ số cũ để không đổi mô hình đối chứng.

LOS proxy dùng `100 × v / free_flow_speed_kmh`, mốc85,67,50,40,30.
Vẫn là proxy: v là trung vị ROI, không phải tốc độ hành trình toàn segment.
Không đổi mẫu số SPI sang tốc độ dòng tự do mà giữ diễn giải tốc độ giới hạn.

Hai bảng cùng có con số50 **không chứng minh chúng tương đương**: mẫu số khác
nhau. Chênh25/30 chỉ so trực tiếp được khi cùng định nghĩa tốc độ và mẫu số;
không coi đó là sai số cố định5 điểm phần trăm trên dữ liệu thực.

## 6. Ngoại suy và tham số kỹ thuật

```text
b = Σ((t−t_mean)(score−score_mean)) / Σ((t−t_mean)²)
a = score_mean − b × t_mean
score_future(h) = clamp(a + b × (t_now + h), 0, 100)
h = 300 hoặc 600 giây
```

Chỉ dùng lịch sử điểm v3 hợp lệ; không dùng điểm thiếu dữ liệu/v1/v2.
Đây là ngoại suy tuyến tính, không phải mô hình học máy được huấn luyện.
R² là độ khớp trong cửa sổ lịch sử, không phải xác suất dự báo đúng.
Lịch sử lấy mẫu tối đa 1 Hz, mặc định cần 300 giây và giữ tối đa 900 giây.
Mất quan sát quá 2 giây, timestamp quay lùi hoặc dữ liệu không hợp lệ sẽ
khởi tạo lại lịch sử/xác nhận trạng thái. Mốc 2 giây là tham số kỹ thuật
bảo vệ tính liên tục, không phải ngưỡng ùn tắc; luồng FPS quá thấp có thể
không đạt điều kiện xác nhận/dự báo. Chuỗi điểm không đổi cho R² không xác định,
không tự nhận độ tin cậy HIGH.
Gửi forecast phụ thuộc cờ `ENABLE_EDGE_FORECAST`; không gửi forecast không
có nghĩa classifier tức thời ngừng hoạt động.

Tối thiểu3 track và xác nhận10 giây là lựa chọn kỹ thuật cần kiểm chứng.
EMA, ROI debounce, snapshot, lọc ngoại lai là tham số pipeline, không phải
thang ùn tắc. Đọc cấu hình thực tế; không mặc định EMA mọi cấu hình đã là0,3.

## 7. Nguồn và giới hạn khoa học

- [He et al. (2016), Procedia Engineering](https://www.sciencedirect.com/science/article/pii/S1877705816003040): nguồn SPI được viện dẫn. Truy cập tự động bản gốc bị403 trong lần kiểm tra này; cần bản gốc và trang/bảng trước khi nộp luận văn.
- [Liao et al. (2023), PLOS ONE, mục Speed performance index](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0279966): trình bày SPI, dẫn He et al.; không chứng minh camera ROI của dự án đã kiểm định.
- [Bảng4 nghiên cứu ETRR (2024)](https://etrr.springeropen.com/articles/10.1186/s12544-024-00701-w/tables/4): bảng tỷ lệ base free-flow speed trích lại HCM; cần đối chiếu đúng ấn bản HCM.
- PCU: bảng TCVN4054:2005 do đề tài cung cấp, chưa đối chiếu bản chính thức trong lần triển khai. Không tuyên bố toàn thuật toán đạt chuẩn TCVN.

Trung vị thay trung bình, gộp bốn mức thành ba nhãn, giới hạn0–100 và xác nhận
thời gian là lựa chọn triển khai. ROI gần đèn có thể điểm cao khi chờ đèn đỏ;
v3 không tự phân biệt nguyên nhân giảm tốc. Tài liệu CASPI trước đó là hướng
khác, không phải công thức này: không thêm trọng số phạt dừng/tự hạ v_ref.

## 8. Kiểm tra và rollback

Chạy cùng video/ROI/hiệu chuẩn cho v1,v2,v3. Gán nhãn thủ công độc lập, gồm
đường vắng, xe dừng từ đầu, đèn đỏ, tắc kéo dài, che khuất, chuyển trạng thái.
Báo cáo precision/recall/F1, sai số tốc độ và tỷ lệ UNKNOWN riêng.
Không bỏ UNKNOWN rồi chỉ báo accuracy trên mẫu dễ.

Rollback: chọn v1/v2, lưu, chạy lại; kiểm tra algorithm_version mới.
Không trộn điểm ba phiên bản thành một thang đo liên tục.

Lịch sử mới lưu phiên bản thuật toán; bản ghi cũ không có phiên bản được đánh
dấu không rõ, không đoán lại từ điểm. Nếu đổi thuật toán trong cùng một phút,
bản ghi tổng hợp phút đó được khởi tạo lại cho phiên bản mới nhất, không giữ
hai thang điểm trong cùng trung bình. Khi làm thí nghiệm A/B cần xuất dữ liệu
riêng từng lượt hoặc chuyển phiên bản sang phút tiếp theo.

Mã liên quan: [classifier](../analytics/traffic_classifier_v3.py),
[Jetson agent](../communication/jetson_agent.py),
[MQTT](../communication/mqtt_client.py),
[API](../webgis/backend/routers/remote_control.py),
[WebGIS](../webgis/frontend/src/components/Fleet/RemoteControlModal.tsx).
