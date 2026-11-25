# Đề cương tài liệu mô tả hệ thống

> **Trạng thái:** Khung nội dung để duyệt, chưa phải bản thuyết minh hoàn chỉnh.  
> **Đối tượng đọc:** Người có kiến thức CNTT cơ bản, chưa biết cấu trúc dự án.  
> **Mục tiêu:** Giúp người đọc hiểu hệ thống làm gì, vì sao chọn kiến trúc/công nghệ đó, dữ liệu đi qua những đâu và cách triển khai/vận hành.

## Quy ước biên soạn

- Viết tiếng Việt làm ngôn ngữ chính. Thuật ngữ tiếng Anh xuất hiện lần đầu phải có giải thích tiếng Việt, ví dụ: **edge computing (điện toán biên)**.
- Phân biệt rõ **đã triển khai**, **đã kiểm chứng**, **được thiết kế nhưng chưa đo**, và **hướng phát triển**.
- Mỗi quyết định kỹ thuật cần trình bày theo mẫu: **vấn đề/yêu cầu → lựa chọn → lý do → đánh đổi/giới hạn → bằng chứng hoặc nguồn**.
- Nguồn ưu tiên: mã nguồn/cấu hình/nhật ký triển khai trong dự án; tài liệu chính thức của nhà cung cấp; tiêu chuẩn hoặc bài báo khoa học. Không xem tài liệu nội bộ là nguồn độc lập để chứng minh một tuyên bố học thuật.
- Không công bố con số hiệu năng, độ chính xác, độ trễ hay mức cải thiện nếu chưa có phép đo tái lập được. Nêu thiết bị, phiên bản, dữ liệu và cách đo đi kèm kết quả.
- Với các kỹ thuật ROI, ước lượng vận tốc và đánh giá ùn tắc, phải truy nguyên tài liệu nền tảng phù hợp; trình bày trung thực phần nào **kế thừa nguyên lý**, phần nào **được điều chỉnh/tham số hóa cho dự án**, và phần nào là **cách tích hợp/triển khai của nhóm**. Không nhận kỹ thuật đã có trong tài liệu là phát minh mới của nhóm, đồng thời không mô tả việc áp dụng một phương pháp có trích dẫn là sao chép.
- Không gán một công thức, ngưỡng hoặc trọng số cho một tiêu chuẩn/tác giả nếu nguồn đó không quy định trực tiếp. Trích dẫn nguồn ngay cạnh kỹ thuật hoặc phát biểu được hỗ trợ; tài liệu nội bộ chỉ làm bằng chứng cho cách dự án hiện thực hóa.
- Phạm vi đánh giá được giới hạn rõ ở nguyên mẫu và các camera/đoạn video, ROI, thiết bị, thời gian thử nghiệm được nêu trong tài liệu. Kết quả chỉ phản ánh điều kiện thử nghiệm đó; không bảo đảm độ chính xác tuyệt đối, tính tổng quát cho mọi tuyến đường, camera, thời tiết hay điều kiện giao thông.

## Mục lục dự kiến

### 1. Giới thiệu và phạm vi hệ thống

**Mục đích:** Nêu bài toán, đối tượng sử dụng và ranh giới hệ thống.

- Bối cảnh giám sát giao thông bằng camera và nhu cầu phân tích gần thời gian thực.
- Hệ thống hỗ trợ việc gì: phân tích tại thiết bị biên, chuyển telemetry về trung tâm, trực quan hóa trên WebGIS, xem video theo yêu cầu.
- Đầu vào, đầu ra và các tác nhân: camera/video, Jetson, MQTT broker, MediaMTX, WebGIS, người vận hành.
- Phạm vi: khu vực/camera đã cấu hình; các lớp phương tiện và trạng thái giao thông mà hệ thống hiện hỗ trợ.
- Ngoài phạm vi: những gì hệ thống chưa cam kết (ví dụ bao phủ toàn đô thị, điều khiển đèn giao thông, hoạt động chính xác trong mọi điều kiện).
- Tuyên bố giới hạn phạm vi ngay từ đầu: đây là nguyên mẫu/triển khai quy mô nhỏ để kiểm chứng tính khả thi của kiến trúc và quy trình; không phải hệ thống điều hành giao thông diện rộng, không khẳng định giải quyết hoàn toàn ùn tắc hay cho kết quả chính xác tuyệt đối.
- Ghi cụ thể phạm vi thử nghiệm khi có dữ liệu: số node/camera, vị trí và góc nhìn, loại nguồn video, thời lượng/tập video, cấu hình Jetson, thời gian đo và các điều kiện chưa khảo sát.

**Hình/bảng dự kiến:** sơ đồ ranh giới hệ thống và bảng thuật ngữ cơ bản.

### 2. Yêu cầu và tiêu chí thiết kế

**Mục đích:** Giải thích các quyết định kiến trúc bắt nguồn từ yêu cầu nào.

- Yêu cầu chức năng: nhận diện/theo dõi, phân tích giao thông, gửi dữ liệu, hiển thị bản đồ/lịch sử, xem live, điều khiển node, lưu ảnh minh chứng.
- Yêu cầu phi chức năng: xử lý tại thiết bị hạn chế tài nguyên, giảm truyền video liên tục, giám sát từ xa, chịu mất mạng ở một số luồng, triển khai và bảo trì được.
- Bảng truy vết: yêu cầu → thành phần đáp ứng → cơ chế → cách kiểm chứng.

**Bằng chứng cần gắn:** endpoint/API, cấu hình, module và phép kiểm chứng tương ứng.

### 3. Kiến trúc tổng thể

**Mục đích:** Cho người đọc bản đồ các thành phần trước khi đi vào chi tiết.

- Edge AI trên Jetson Nano: nguồn video, DeepStream/GStreamer, TensorRT, tracker, analytics, agent và MQTT client.
- Trung tâm WebGIS: Auth Service, FastAPI backend, frontend, lưu trữ/cache.
- Hạ tầng trao đổi: MQTT broker, HTTP/REST, WebSocket, MediaMTX và các giao thức video.
- Ranh giới trách nhiệm, giao tiếp và điểm lỗi chính giữa các thành phần.

**Hình dự kiến:** sơ đồ kiến trúc duy nhất, mỗi luồng có màu và số thứ tự; phân biệt luồng video với luồng metadata/lệnh.

### 4. Nền tảng triển khai và phiên bản

**Mục đích:** Ghi lại môi trường thật và giải thích lựa chọn theo tương thích, không biến danh sách phiên bản thành tuyên bố quảng cáo.

- **Edge Jetson:** model board, RAM, GPU/SoC, JetPack, CUDA, cuDNN, DeepStream, TensorRT, Python, GStreamer, OpenCV/PyDS.
- **WebGIS server:** hệ điều hành, Python và phiên bản thư viện backend; Node.js/npm và thư viện auth; trình duyệt/môi trường chạy frontend.
- **Triển khai:** Docker/Compose, MediaMTX và cấu hình mạng/cổng.
- Với mỗi phiên bản: phiên bản khai báo và phiên bản cài thực tế; yêu cầu tương thích; lý do chọn; ưu/nhược; nguồn chính thức.
- Phân biệt phiên bản Edge và phiên bản Backend. Không suy ra phiên bản runtime chỉ từ `requirements.txt` nếu file dùng ràng buộc `>=`.

**Bảng dự kiến:** Thành phần | Phiên bản khai báo | Phiên bản thực tế | Lý do/tương thích | Hạn chế | Nguồn.

**Nguồn cần thu thập khi viết bản đầy đủ:** NVIDIA Jetson Linux/JetPack compatibility matrix, DeepStream/TensorRT release documentation, Docker/MediaMTX docs và manifest/lockfile của dự án. Cần đối chiếu trực tiếp thiết bị trước khi chốt.

### 5. Công nghệ và quyết định thiết kế

**Mục đích:** Giải thích “vì sao dùng công nghệ này trong hệ thống này”, không chỉ định nghĩa công nghệ.

Các tiểu mục dự kiến:

1. DeepStream và GStreamer: pipeline xử lý video, thành phần phần cứng và tích hợp plugin.
2. YOLO/TensorRT và độ chính xác FP16: định dạng suy luận, lý do cân nhắc trên Jetson, đánh đổi độ chính xác cần đo.
3. Tracker và inference interval: duy trì định danh giữa các lần detector chạy; ảnh hưởng đến tải và nguy cơ mất dấu.
4. ROI, homography (biến đổi phối cảnh) và hồi quy vận tốc: dữ liệu hiệu chuẩn cần có và giả định mặt đường.
5. MQTT: telemetry/lệnh nhẹ, topic, QoS/TLS nếu cấu hình thực tế có bật.
6. REST/HTTP và WebSocket: tác vụ yêu cầu/đáp ứng so với cập nhật trạng thái liên tục.
7. MediaMTX, RTSP, WebRTC/LL-HLS: nhận video từ edge và phục vụ trình duyệt.
8. FastAPI, React/TypeScript, Node.js/Express, SQLite và xác thực/phân quyền: trách nhiệm từng dịch vụ và giới hạn quy mô hiện tại.

**Bảng dự kiến:** Công nghệ | Vai trò trong dự án | Yêu cầu giải quyết | Lý do chọn | Đánh đổi | Tài liệu tham khảo.

### 6. Luồng dữ liệu và luồng điều khiển

**Mục đích:** Theo một sự kiện từ đầu vào đến người dùng và làm rõ mỗi giao thức đáp ứng nhu cầu nào.

- **Luồng phân tích:** camera/video → giải mã/tiền xử lý → detector → tracker → ROI/analytics → trạng thái/điểm số.
- **Luồng telemetry:** kết quả tổng hợp → MQTT → FastAPI → cập nhật trạng thái/lịch sử → WebSocket/API → dashboard.
- **Luồng live theo yêu cầu:** người dùng yêu cầu xem → API/backend → lệnh MQTT → Jetson mở nhánh video → encoder/RTSP → MediaMTX → WebRTC hoặc HLS tới trình duyệt; dừng/timeout đóng nhánh.
- **Luồng ảnh minh chứng:** điều kiện kích hoạt → chụp ảnh → outbox cục bộ → HTTP upload/retry → xác nhận thành công/xóa theo chính sách.
- **Luồng điều khiển node:** người dùng có quyền → API → lệnh → command router trên edge → thao tác được cho phép → phản hồi/trạng thái.
- Với mỗi luồng: payload chính, nơi xử lý, giao thức, tần suất/kích hoạt, hành vi lỗi và yêu cầu được đáp ứng.

**Hình dự kiến:** sequence diagram (sơ đồ tuần tự) cho luồng xem live và luồng outbox; data-flow diagram (sơ đồ luồng dữ liệu) cho pipeline chính.

### 7. Logic phân tích giao thông

**Mục đích:** Trình bày đủ để hiểu đầu vào, giả định, công thức và giới hạn.

- Phát hiện và theo dõi đối tượng; định nghĩa ID track và ROI.
- Ước lượng vận tốc: điểm tiếp đất, hiệu chuẩn bốn điểm, ma trận homography, timestamp, cửa sổ quan sát/lọc nhiễu.
- Tính toán số lượng/mật độ/PCE và tỷ lệ phương tiện dừng theo logic đang có trong mã.
- Mô hình điểm ùn tắc: thành phần, trọng số, ngưỡng FREE/SLOW/CONGESTED, làm mượt trạng thái và các guard.
- Nguồn của từng công thức/ngưỡng: tài liệu tham khảo, quyết định thiết kế của nhóm hay tham số hiệu chỉnh thực nghiệm.
- Với mỗi phần thuật toán, lập một bảng truy nguyên học thuật: **kỹ thuật trong dự án → tài liệu gốc/nguồn đáng tin cậy → nguyên lý được sử dụng → khác biệt/cách điều chỉnh trong mã → bằng chứng kiểm chứng → giới hạn**.
- ROI: giải thích ROI (region of interest — vùng quan tâm) là cách giới hạn phân tích vào vùng ảnh phù hợp; dẫn tài liệu nền tảng về xử lý ảnh/giám sát giao thông khi xác lập phương pháp và mô tả chính xác cách dự án lưu/vẽ vùng đa giác, kiểm tra điểm và dùng ROI. Không tuyên bố rằng khái niệm ROI do nhóm đề xuất.
- Vận tốc: dẫn tài liệu về hiệu chuẩn camera, phép biến đổi phối cảnh/homography và ước lượng vận tốc từ chuỗi vị trí theo thời gian; giải thích giả định camera cố định, mặt đường gần phẳng, cần biết kích thước/điểm chuẩn. Mô tả cách dự án chọn điểm đại diện, ánh xạ tọa độ, lọc và làm mượt; nêu các sai số đo được hoặc chưa đo.
- Mô hình ùn tắc: tách rõ cơ sở giao thông (tốc độ, mật độ, tỷ lệ dừng, quy đổi PCE/LOS nếu thực sự áp dụng) khỏi công thức điểm và ngưỡng do dự án lựa chọn. Dẫn nguồn cho từng đại lượng/nguyên lý; nếu trọng số/ngưỡng là heuristic (quy tắc kinh nghiệm) hoặc được hiệu chỉnh trong dự án, ghi rõ là quyết định thiết kế/hiệu chỉnh của nhóm, không gán nguyên xi cho tài liệu tham khảo.
- Dùng các động từ phù hợp: “áp dụng”, “kế thừa nguyên lý”, “điều chỉnh”, “tích hợp”, “hiện thực hóa” hoặc “đánh giá”; chỉ dùng “đề xuất mới” nếu có đóng góp mới được xác định và so sánh với công trình liên quan.
- Giới hạn và các ca khó: camera rung/thay góc, che khuất, track đổi ID, xe máy đi sát, ánh sáng, sai số hiệu chuẩn, mẫu ít.
- Nếu đưa dự báo, phải phân biệt hồi quy ngoại suy xu hướng với mô hình học máy đã huấn luyện.

**Bảng dự kiến:** Đại lượng | Cách tính trong hệ thống | Tham số/giả định | Nguồn hoặc căn cứ | Giới hạn.

**Bảng nguồn học thuật dự kiến:** Thành phần | Nguồn nền tảng | Nội dung nguồn hỗ trợ | Cách dự án sử dụng/điều chỉnh | Tệp mã/cấu hình đối chiếu | Mức độ kiểm chứng. Bảng này nhằm cho thấy cơ sở kỹ thuật và ranh giới đóng góp, không nhằm khẳng định mọi tham số của dự án đã được chứng minh bởi một tài liệu duy nhất.

### 8. Kiến trúc phần mềm và cấu trúc mã

**Mục đích:** Chỉ ra cách phân rã module để người đọc định vị chức năng.

- Edge: `main.py`, `core/`, `analytics/`, `spatial/`, `communication/`, `snap/`, `config/`, `configs/`.
- WebGIS: frontend, FastAPI backend, auth-service, data store và routers.
- Nguyên tắc phân tách: pipeline video, logic nghiệp vụ, truyền thông, giao diện và xác thực.
- Hợp đồng dữ liệu giữa các module/dịch vụ và cấu hình môi trường.

**Hình/bảng dự kiến:** sơ đồ module và bảng thư mục → trách nhiệm → điểm vào chính.

### 9. Triển khai và vận hành

**Mục đích:** Mô tả cách triển khai theo các chế độ thật của dự án.

- WebGIS development trên Windows: vai trò `start_webgis.bat`, kiểm tra Python/Node, phụ thuộc, MediaMTX và các tiến trình dịch vụ.
- WebGIS production/local package và triển khai Docker Compose: thành phần, cổng, volume, biến môi trường, phụ thuộc khởi động.
- Edge Jetson: cấu hình `.env`, model/config, camera CSI/file/RTSP, khởi chạy pipeline/service và tự khởi động nếu được cấu hình.
- Cấu hình node/ROI, tạo tài khoản, broker, địa chỉ mạng và firewall.
- Dừng/restart, log, kiểm tra sức khỏe và xử lý các sự cố vận hành phổ biến.
- Phân biệt cấu hình demo, development và production; nêu rõ bước nào đang thủ công.

**Hình dự kiến:** sơ đồ triển khai (deployment diagram) và checklist triển khai ngắn.

### 10. Bảo mật, độ tin cậy và xử lý lỗi

**Mục đích:** Mô tả cơ chế đã có và ranh giới tin cậy.

- Auth/JWT/RBAC và quyền của từng vai trò.
- Whitelist lệnh từ xa; bảo vệ secret; MQTT TLS nếu cấu hình.
- Timeout/heartbeat/offline status; retry/outbox; giới hạn dung lượng/lưu ảnh.
- Hành vi khi mất camera, mất broker, backend, MediaMTX hoặc mạng.
- Những rủi ro còn lại và biện pháp vận hành tương ứng; chỉ ghi tính năng đã xác minh trong mã/cấu hình.

### 11. Đánh giá và bằng chứng

**Mục đích:** Tách minh chứng chức năng khỏi kết luận định lượng.

- Kiểm thử chức năng theo module và luồng đầu cuối; cách tái lập.
- Đo pipeline: FPS, độ trễ, CPU/GPU/RAM, nhiệt độ, thời gian chạy và điều kiện đo.
- Đo detector/ước lượng vận tốc/phân loại ùn tắc bằng ground truth (giá trị chuẩn) nếu có.
- So sánh có kiểm soát: cấu hình pipeline, FP32/FP16, hoặc phiên bản classifier; giữ dữ liệu/điều kiện tương đương.
- Tập dữ liệu, cách gán nhãn, metrics (chỉ số), kết quả, sai số và giới hạn.
- Bảng kết quả để trống đến khi có số đo đã lưu và có thể tái lập.

### 12. Giới hạn và hướng phát triển

- Giới hạn thiết bị, góc camera, hiệu chuẩn và dữ liệu.
- Khả năng mở rộng số node, lưu trữ lịch sử và quản lý mạng.
- Các cải tiến có thứ tự ưu tiên, gắn với giới hạn đã nêu; phân biệt kế hoạch với phần đã hoàn thành.

### 13. Tài liệu tham khảo và phụ lục

- Tài liệu chính thức theo phiên bản phần mềm/phần cứng.
- Tiêu chuẩn, bài báo, nguồn công thức/thuật toán; trích dẫn ngay tại mục liên quan.
- Bảng thuật ngữ Anh–Việt, topic/payload mẫu đã loại bỏ thông tin bí mật, ports, cấu hình triển khai, checklist chạy thử và danh sách phiên bản.

## Phạm vi và cách diễn đạt kết luận (áp dụng xuyên suốt)

Tài liệu sẽ xác định hệ thống là một **nguyên mẫu Edge AIoT/WebGIS quy mô nhỏ**, được triển khai và đánh giá trong phạm vi thiết bị, camera/nguồn video, ROI và môi trường thử nghiệm cụ thể của dự án. Mục tiêu là chứng minh quy trình tích hợp và đánh giá tính khả thi, không tuyên bố bao phủ mọi bối cảnh giao thông hoặc thay thế hệ thống giám sát chuyên dụng.

Kết luận về ROI, vận tốc và trạng thái ùn tắc phải kèm điều kiện áp dụng. Kết quả phụ thuộc vào góc đặt và độ ổn định camera, chất lượng hiệu chuẩn, khả năng phát hiện/theo dõi, cấu hình ngưỡng, nguồn video và điều kiện môi trường. Tài liệu sẽ nêu rõ phần nào đã được kiểm thử, phần nào mới có kiểm thử chức năng, phần nào chưa có ground truth (giá trị chuẩn) hoặc chưa đủ mẫu để đánh giá định lượng.

## Khung truy nguyên tài liệu cho các kỹ thuật chính

| Phần của hệ thống | Cơ sở tài liệu cần tìm/đối chiếu | Điều cần xác nhận trước khi viết khẳng định |
|---|---|---|
| ROI và hình học ảnh | Tài liệu xử lý ảnh/giám sát giao thông về vùng quan tâm, đa giác và điểm thuộc vùng; tài liệu thư viện dùng trong mã | Phương pháp nào là nguyên lý phổ biến; cách vẽ/lưu/chọn ROI nào là triển khai cụ thể của dự án |
| Homography và vận tốc | Giáo trình/tài liệu thị giác máy tính về hiệu chuẩn phối cảnh; nghiên cứu camera giao thông ước lượng vận tốc từ điểm ảnh và thời gian | Giả định camera/mặt phẳng; loại điểm đại diện; cách biến đổi và lọc vận tốc; nguồn sai số |
| Điểm ùn tắc | Tài liệu giao thông về tốc độ, mật độ, lưu lượng, PCE/LOS; nghiên cứu phân loại ùn tắc phù hợp bối cảnh camera | Đại lượng nào có căn cứ nguồn; công thức tổng hợp, trọng số và ngưỡng nào do dự án tự chọn/hiệu chỉnh |
| DeepStream/TensorRT/FP16 | Tài liệu NVIDIA đúng phiên bản và kiến trúc GPU/JetPack đang chạy | Tương thích phiên bản, hỗ trợ phần cứng thực tế, chất lượng và hiệu năng đo được; không suy diễn mức tăng tốc nếu chưa benchmark |

Các hàng trên là **định hướng tìm nguồn**, chưa phải trích dẫn thư mục đã xác minh. Bản đầy đủ chỉ ghi tên tác giả, năm, tiêu chuẩn, công thức hoặc kết luận sau khi đối chiếu tài liệu gốc và xác nhận nội dung nguồn hỗ trợ đúng phát biểu.

## Đầu vào cần có khi phát triển thành bản đầy đủ

- Phiên bản thực tế trên Jetson (ảnh/log lệnh hệ thống) và cấu hình thiết bị.
- Tài liệu gốc hoặc bài báo mà nhóm đã dùng khi chọn phương pháp ROI, hiệu chuẩn/vận tốc, đại lượng giao thông và mô hình phân loại ùn tắc. Nếu chưa lưu, sẽ truy tìm từ các nguồn học thuật/chính thức phù hợp rồi đối chiếu công thức và cách triển khai trong mã.
- Log benchmark, tập video và nhãn tham chiếu nếu muốn đưa kết luận định lượng. Nếu chưa có, tài liệu sẽ ghi phần đó là chưa được đánh giá định lượng, không tự điền số liệu.
- Độ dài mặc định khi viết bản đầy đủ: khoảng 20–30 trang nội dung chính, phần phiên bản/cấu hình và tài liệu kỹ thuật chi tiết đặt ở phụ lục.
