# Mô tả phương án phân tích giao thông bằng chỉ số SPI

Ngày đối chiếu triển khai: 22 tháng 11 năm 2026.

Phương án sử dụng camera cố định để phát hiện và theo dõi phương tiện, ước lượng tốc độ trên mặt đường, sau đó tính chỉ số hiệu suất tốc độ SPI và hiển thị trạng thái giao thông trên WebGIS. Mục tiêu là cung cấp chỉ báo suy giảm tốc độ tại vùng quan sát phục vụ giám sát, không thay thế phép đo tốc độ được kiểm định hoặc đánh giá năng lực thông hành chính thức.

## 1 Phạm vi và phiên bản

Tài liệu mô tả đường chạy v3 trong mã nguồn hiện tại: [main.py](../main.py), [traffic_classifier_v3.py](../analytics/traffic_classifier_v3.py), [traffic_classifier.py](../analytics/traffic_classifier.py) và [speed_estimator.py](../analytics/speed_estimator.py).

Kết quả phân loại cuối của v3 hiện dùng **trung bình cộng tốc độ**, không dùng trung vị. Bộ phân tích chung vẫn tính trung vị để báo cáo và một đường phân loại trung gian có thể nhận trung vị; không được lấy bước trung gian đó làm mô tả cho kết quả cuối. Các log của phiên bản cũ dùng trung vị phải được phân tích riêng, không gộp với kết quả hiện tại dưới cùng một mô tả phương pháp.

Trước khi thí nghiệm cần cố định phiên bản mã và lưu cấu hình thực tế. Các phiên bản v1/v2 chỉ là đối chứng khi được chạy có kiểm soát; tài liệu này không mô tả chúng như thuật toán SPI.

## 2 Đầu vào

| Nhóm | Dữ liệu cần có | Vai trò |
| --- | --- | --- |
| Video | Khung hình, timestamp, thông tin FPS nguồn | Phát hiện và xác định khoảng thời gian chuyển động |
| Phát hiện | Hộp bao, lớp đối tượng, độ tin cậy | Cung cấp quan sát cho bộ theo dõi |
| Theo dõi | Track ID và lịch sử vị trí | Liên kết cùng phương tiện giữa các khung hình |
| Vùng đo | Analysis ROI, vùng phát hiện, vùng loại trừ nếu có | Chọn nhóm phương tiện được phân tích |
| Hiệu chuẩn | Bốn điểm ảnh và bốn điểm mặt đường tương ứng theo mét | Xây dựng phép biến đổi homography |
| Tham chiếu | reference_speed_kmh dương | Mẫu số của SPI |
| Chất lượng | minimum_valid_tracks, status_confirm_seconds | Điều kiện đủ dữ liệu và ổn định trạng thái |

Tốc độ tham chiếu của phương án được chọn theo giới hạn tốc độ đã xác minh cho hướng và đoạn đường quan sát. Nếu dùng giá trị giả định trong video thử nghiệm, phải ghi rõ đó là kịch bản giả định; không trình bày kết quả như đánh giá thực địa. Tốc độ giới hạn khác tốc độ dòng tự do đo khi ít bị cản trở.

Mỗi góc camera cần hiệu chuẩn riêng. Không dùng nguyên bốn điểm và kích thước mặt đường của video này cho video khác. Độ phân giải video gốc phải được phân biệt với độ phân giải chuẩn hóa của pipeline.

## 3 Quy trình xử lý

1. Giải mã và chuẩn hóa khung hình; mô hình phát hiện cung cấp hộp bao và lớp phương tiện.
2. Bộ theo dõi gán track ID và cập nhật lịch sử vị trí.
3. Dùng trung điểm cạnh dưới hộp bao làm điểm đại diện gần vị trí tiếp xúc mặt đường; xác nhận sự hiện diện trong ROI có trễ vào/ra để hạn chế dao động sát biên.
4. Chuyển vị trí ảnh sang tọa độ mặt đường, ước lượng và làm mượt tốc độ từng track.
5. Tổng hợp tốc độ của các track thuộc ROI, sau khi áp dụng vùng loại trừ.
6. Kiểm tra dữ liệu và tốc độ tham chiếu; tính SPI khi đủ điều kiện.
7. Ánh xạ mức SPI sang nhãn giao thông, xác nhận nhãn theo thời gian và gửi telemetry.
8. Backend lưu lịch sử; WebGIS hiển thị trạng thái và chỉ số kèm chất lượng dữ liệu.

## 4 Công thức tốc độ

### 4.1 Biến đổi tọa độ

Với điểm ảnh (u, v), ma trận homography H ánh xạ đến điểm mặt đường (X, Y):

```text
[a, b, c]ᵀ = H [u, v, 1]ᵀ
X = a/c
Y = b/c
```

X và Y tính bằng mét. Bốn cặp điểm hiệu chuẩn phải cùng thứ tự và mô tả cùng các vị trí thực. Phương pháp giả định mặt đường gần phẳng và camera cố định. Nghiên cứu của Bell và cộng sự là nguồn tham khảo về ước lượng tốc độ từ camera đơn và kiểm chứng bằng dữ liệu quỹ đạo độc lập [3].

### 4.2 Tốc độ từng phương tiện

Trong cửa sổ lịch sử của track i, hồi quy riêng hai tọa độ theo thời gian:

```text
X_i(t) ≈ a_x t + b_x
Y_i(t) ≈ a_y t + b_y
v_raw,i = 3,6 × sqrt(a_x² + a_y²)       [km/h]
v_hat,i(t) = α v_raw,i(t) + (1 − α) v_hat,i(t−1)
```

Nếu chưa đủ lịch sử thì chưa có tốc độ hợp lệ. Nếu chuyển vị trong cửa sổ nhỏ hơn ngưỡng kỹ thuật thì tốc độ thô được đặt bằng 0; đây không phải bằng chứng độc lập rằng xe đã dừng hoàn toàn. Các bước lọc tốc độ và gián đoạn track nhằm hạn chế sai số theo dõi, không phải ngưỡng phân loại ùn tắc.

Thời gian phải dựa trên thời gian nguồn video. FPS xử lý trên Jetson không tự động bằng FPS camera. Với H264 thô, cần xác minh timestamp/FPS và cơ chế dự phòng trước khi dùng kết quả km/h cho nghiên cứu định lượng.

### 4.3 Tốc độ đại diện trong ROI

Gọi V_t là tập track có tốc độ hợp lệ trong ROI tại thời điểm t, N_t là số phần tử:

```text
v_avg(t) = Σ v_hat,i(t) / N_t, với i thuộc V_t
```

Mỗi track đóng góp một giá trị trong một lần cập nhật. Cùng phương tiện có thể góp mặt ở nhiều lần cập nhật khi còn trong ROI. Cửa sổ lịch sử ước lượng tốc độ từng xe không đồng nghĩa với cửa sổ lấy trung bình tất cả xe đã đi qua đoạn đường.

Trong đường chạy chính hiện tại, xe chưa từng di chuyển không bị loại chỉ vì cờ has_moved=False. Quyết định này cho phép quan sát xe chờ đèn nhưng cũng khiến xe đỗ trong ROI có thể làm giảm tốc độ đại diện; cần cấu hình vùng loại trừ hợp lý.

## 5 SPI và điểm hiển thị

Các nghiên cứu SPI mô tả tỷ số tốc độ trung bình so với tốc độ tham chiếu và các mức chia 25, 50, 75 [1, 2]. Triển khai sử dụng:

```text
SPI_raw = 100 × v_avg / v_ref
SPI = min(100, max(0, SPI_raw))
C = 100 − SPI
```

SPI cao biểu thị tốc độ gần hoặc vượt tham chiếu; C cao biểu thị suy giảm tốc độ lớn. Phép chặn 0–100 và điểm phần bù C là quy tắc triển khai. C không phải xác suất ùn tắc và không phải chỉ số học từ dữ liệu.

| Khoảng SPI triển khai | Mức SPI | Nhãn thô WebGIS | Khoảng C |
| --- | --- | --- | --- |
| 0 ≤ SPI ≤ 25 | HEAVY_CONGESTION | CONGESTED | 75 ≤ C ≤ 100 |
| 25 < SPI ≤ 50 | MILD_CONGESTION | SLOW | 50 ≤ C < 75 |
| 50 < SPI ≤ 75 | SMOOTH | FREE | 25 ≤ C < 50 |
| 75 < SPI ≤ 100 | VERY_SMOOTH | FREE | 0 ≤ C < 25 |

Việc gộp hai mức thông thoáng thành FREE và quy định giá trị đúng tại biên là lựa chọn tích hợp của dự án. Không xem bốn mức SPI là tương đương trực tiếp với HCM LOS A–F. Tốc độ ROI ngắn không phải tốc độ hành trình của toàn segment.

Ví dụ minh họa với v_ref=40 km/h và đủ dữ liệu:

| v_avg | SPI | C | Nhãn thô |
| --- | --- | --- | --- |
| 30 km/h | 75 | 25 | FREE |
| 15 km/h | 37,5 | 62,5 | SLOW |
| 8 km/h | 20 | 80 | CONGESTED |

Đây là ví dụ tính toán, không phải kết quả thí nghiệm của hệ thống.

## 6 Chất lượng dữ liệu và xác nhận trạng thái

Không có xe, chưa có tốc độ hữu hạn, thiếu số track tối thiểu hoặc thiếu tham chiếu hợp lệ đều không được suy thành FREE hay CONGESTED. Kết quả cần được đọc cùng data_quality và reason.

Số xe phát hiện và số track có tốc độ hợp lệ là hai đại lượng khác nhau. Ví dụ, ROI có 3 xe nhưng chỉ 2 tốc độ hợp lệ vẫn không đủ nếu minimum_valid_tracks=3.

Nhãn mới chỉ được xác nhận khi ứng viên duy trì đủ status_confirm_seconds theo timestamp phân tích. Trong lúc chờ, kết quả có thể giữ nhãn ổn định trước đó hoặc UNKNOWN nếu chưa từng xác nhận. Do đó điểm tức thời và màu trạng thái có thể khác nhau.

Trong mã hiện tại, quan sát không hợp lệ trả UNKNOWN và xóa ứng viên đang chờ nhưng không xóa biến nhãn ổn định trước đó. Khi dữ liệu trở lại cùng nhãn ổn định cũ, nhãn có thể được trả lại ngay. Đây là hành vi cần mô tả đúng khi đánh giá độ trễ và tỷ lệ UNKNOWN, không giả định mọi lần phục hồi đều phải chờ lại đủ thời gian.

## 7 Đầu ra và cách đọc trên WebGIS

| Trường | Ý nghĩa |
| --- | --- |
| avg_speed_kmh | Tốc độ trung bình ROI, dùng cho kết quả SPI cuối trong phiên bản hiện tại |
| median_speed_kmh nếu có | Thống kê bổ trợ; không mặc nhiên là đầu vào SPI |
| reference_speed_kmh | Tốc độ tham chiếu đã cấu hình |
| valid_speed_tracks | Số track có tốc độ hợp lệ |
| spi và spi_level | Chỉ số đã chặn và một trong bốn mức SPI |
| speed_ratio_percent | Tỷ số tốc độ chưa chặn; có thể lớn hơn 100 |
| speed_reduction_index | Điểm phần bù 100 − SPI |
| traffic_status hoặc traffic_state | Trạng thái trả về sau bước xác nhận |
| data_quality và reason | Chất lượng dữ liệu và lý do không kết luận |
| status_pending | Có đang chờ xác nhận thay đổi trạng thái hay không |
| current_vehicle_count và counts_by_class | Số xe hiện diện và phân bố lớp |

Đọc điểm v3 từ speed_reduction_index; không giả định trường congestion_score kế thừa luôn chứa cùng đại lượng. Bộ v3 hiện không ghi đè SPI vào congestion_score. Giao diện phải ưu tiên trạng thái backend trả về và thể hiện giá trị thiếu bằng dấu gạch, không biến thiếu dữ liệu thành điểm 0 mang nghĩa thông thoáng.

PCE không tham gia công thức SPI. Bộ phân loại v3 hiện truyền pce=None; nếu báo cáo mật độ quy đổi từ lớp xử lý khác, cần khai báo riêng công thức và hệ số thực dùng. Không khẳng định mọi hệ số lớp truck/bus chung đều tương ứng nguyên văn với tiêu chuẩn thiết kế đường.

## 8 Cấu hình kỹ thuật

Các giá trị sau là mặc định trong đường khởi tạo chính hoặc tham số CLI ở thời điểm đối chiếu, không phải giá trị bắt buộc trong mọi phiên chạy:

| Tham số | Giá trị | Vai trò |
| --- | --- | --- |
| minimum_valid_tracks | 3 nếu không bị cấu hình ghi đè | Số tốc độ hợp lệ tối thiểu |
| status_confirm_seconds | Đọc từ CLI hoặc cấu hình thực tế | Xác nhận thay đổi nhãn; phải ghi giá trị của phiên đo |
| speed-min-time | 0,80 s | Lịch sử tối thiểu để tính tốc độ |
| speed-min-displacement | 0,35 m | Ngưỡng chuyển vị nhỏ |
| speed-smoothing-alpha | 0,25 | Hệ số EMA |
| speed-max-gap | 0,75 s | Giới hạn khoảng cách thời gian giữa mẫu track |
| speed-max-kmh | 130 km/h | Giới hạn lọc tốc độ |
| Ngưỡng SPI dùng ở main | 50 và 25 | Ánh xạ FREE/SLOW/CONGESTED |

Hàm/lớp v3 có một số mặc định khác đường main, nên khi gọi độc lập phải truyền cấu hình rõ ràng. Chỉ dùng số trong cấu hình mặc định để mô tả thí nghiệm là chưa đủ.

## 9 Giới hạn của phép phân tích

1. ROI camera là vùng quan sát ngắn; đại lượng đo không tương đương trực tiếp tốc độ hành trình của cả đoạn đường.
2. Xe chờ pha đỏ làm SPI thấp dù hàng chờ có thể giải phóng trong pha xanh tiếp theo. CONGESTED không tự chứng minh ùn tắc kéo dài hoặc quá tải năng lực thông hành.
3. Sai điểm hiệu chuẩn, kích thước mặt đường, timestamp hoặc FPS làm sai tốc độ km/h và kéo theo sai SPI.
4. Che khuất, mất ID, rung hộp bao, góc nhìn xa và xe máy đi sát nhau ảnh hưởng độ tin cậy của track.
5. Mẫu tại một thời điểm có thể thiên về xe chậm do chúng ở lâu trong ROI; không coi trung bình quan sát là mẫu ngẫu nhiên của tất cả xe đi qua.
6. Chưa có đối chiếu độc lập thì chỉ kết luận được nguyên mẫu vận hành và tạo chỉ số, chưa kết luận được độ chính xác phân loại thực địa.

## 10 Kế hoạch đánh giá

### 10.1 Dữ liệu và tái lập

Lưu cho mỗi video: nguồn, quyền sử dụng, độ phân giải gốc, số khung hình, FPS đã xác minh, điều kiện đèn, cấu hình ROI, kích thước hiệu chuẩn, nguồn xác minh tốc độ tham chiếu, phiên bản mã và các tham số kỹ thuật. Không trộn phiên bản trung bình với trung vị trong cùng bảng kết quả mà không phân nhóm.

### 10.2 Độ chính xác tốc độ

Đối chiếu tốc độ từng xe với dữ liệu độc lập, báo số mẫu, MAE và RMSE theo km/h. Nếu dùng hai vạch có khoảng cách biết trước, khoảng cách và thời điểm qua vạch phải được xác định độc lập với phép biến đổi cần kiểm chứng. Không ưu tiên MAPE khi tốc độ tham chiếu gần 0.

### 10.3 Trạng thái và khả năng cung cấp kết quả

Có nhãn giao thông độc lập thì báo ma trận nhầm lẫn, precision/recall/F1 từng lớp và quy trình gán nhãn. Nhãn tính lại bằng cùng công thức SPI chỉ kiểm tra tính đúng của chương trình, không kiểm chứng giá trị thực tiễn của ngưỡng.

```text
Coverage = số thời điểm có dữ liệu hợp lệ / tổng thời điểm đánh giá
```

Tách tỷ lệ đủ dữ liệu, tỷ lệ đã xác nhận nhãn và tỷ lệ UNKNOWN theo nguyên nhân. Khi chu kỳ lấy mẫu không đều, dùng thời lượng tương ứng thay vì đếm mẫu đơn thuần. Báo riêng pha đỏ/pha xanh hoặc chu kỳ đèn để đánh giá sai báo do dừng tín hiệu.

### 10.4 Hiệu năng thiết bị

Đo FPS, CPU/GPU, RAM, nhiệt độ, công suất và mạng trong cùng khoảng thời gian với video. [system_metrics.py](../communication/system_metrics.py) phục vụ sức khỏe thiết bị; [measure_jetson.py](../measure_jetson.py) và [collect_tegrastats.sh](../tools/collect_tegrastats.sh) phục vụ thu thập benchmark. Hai đường thu thập không được mặc nhiên coi là cùng nguồn.

Phân biệt CPU/RAM tiến trình với CPU/RAM toàn máy; công suất đo với chế độ nguồn; lưu lượng toàn card mạng với lưu lượng MQTT; FPS xử lý với FPS nguồn. Trường power_mode cố định không chứng minh công suất thực. Thiếu số đo phải ghi không thu thập được, không thay bằng 0. Tài liệu NVIDIA giải thích các trường phần cứng của tegrastats [4].

## 11 Đoạn mô tả có thể dùng trong bài báo

Hệ thống ước lượng trạng thái giao thông từ tốc độ của phương tiện trong vùng quan sát của camera cố định. Vị trí đại diện của từng phương tiện được ánh xạ sang mặt phẳng đường bằng homography; tốc độ được tính từ hồi quy tọa độ theo thời gian và làm mượt bằng EMA. Tại mỗi lần cập nhật, trung bình tốc độ của các track hợp lệ được chuẩn hóa theo tốc độ tham chiếu để tính SPI. Các mốc 25, 50 và 75 được tham khảo từ nghiên cứu SPI, trong khi phép gộp thành ba nhãn hiển thị, điều kiện đủ số track và thời gian xác nhận là các lựa chọn triển khai. Chỉ số phản ánh suy giảm tốc độ tại ROI, chưa thay thế đánh giá ùn tắc của toàn đoạn đường hoặc phân biệt được dừng chờ đèn với ùn tắc kéo dài. Độ chính xác cần được đánh giá bằng dữ liệu tham chiếu độc lập.

## 12 Tài liệu tham khảo

1. Liao, L., et al. (2023). An expressway traffic congestion measurement under the influence of service areas. PLOS ONE, 18(1), e0279966. [Toàn văn, mục Speed performance index và phương trình 7](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0279966). Phạm vi nghiên cứu là cao tốc có khu dịch vụ, không phải kiểm chứng trực tiếp ROI tại nút giao đô thị.
2. Afrin, T., & Yodo, N. (2020). A Survey of Road Traffic Congestion Measures towards a Sustainable and Resilient Transportation System. Sustainability, 12(11), 4660. [Mục 3.1.2 và Bảng 1](https://www.mdpi.com/2071-1050/12/11/4660).
3. Bell, D., Xiao, W., & James, P. (2020). Accurate Vehicle Speed Estimation from Monocular Camera Footage. ISPRS Annals, V-2-2020, 419–426. [DOI và toàn văn](https://isprs-annals.copernicus.org/articles/V-2-2020/419/2020/).
4. NVIDIA. Jetson Linux Developer Guide, Tegrastats Utility. [Tài liệu chính thức](https://docs.nvidia.com/jetson/l4t/Tegra%20Linux%20Driver%20Package%20Development%20Guide/AppendixTegraStats.html).
5. He, F., Yan, X., Liu, Y., & Ma, L. (2016). A Traffic Congestion Assessment Method for Urban Road Networks Based on Speed Performance Index. Procedia Engineering, 137, 425–433. [DOI](https://doi.org/10.1016/j.proeng.2016.01.277). Đây là công trình nền tảng được các nguồn [1, 2] dẫn lại; khi trích bảng hoặc phát biểu cụ thể trực tiếp từ [5], cần đối chiếu bản toàn văn gốc.

Các tài liệu khoa học hỗ trợ lựa chọn phương pháp, không phải văn bản chứng nhận pháp lý hoặc chứng nhận độ chính xác cho hệ thống triển khai.
