export function TrafficUsageHelp() {
  return <details className="rounded-xl border border-blue-200 bg-blue-50 p-3 text-xs text-slate-700">
    <summary className="cursor-pointer font-semibold text-blue-900">Cách dùng và đọc SPI v3</summary>
    <div className="mt-2 space-y-2 leading-relaxed">
      <p>SPI = 100 × v / v tham chiếu; v là trung vị tốc độ các xe hợp lệ. Điểm ùn tắc = 100 − SPI (giới hạn 0–100).</p>
      <p>Điểm &lt; 50: thông thoáng; 50 đến dưới 75: chậm; ≥ 75: ùn tắc. Tương ứng SPI &gt; 50, 25 &lt; SPI ≤ 50, SPI ≤ 25.</p>
      <p>Nhập tốc độ tham chiếu theo biển báo/giới hạn được xác minh tại đoạn đường. OSM chỉ để tham khảo; tốc độ mặc định không phải giới hạn đã xác minh.</p>
      <p>Tốc độ dòng tự do (FFS) là tốc độ quan sát khi xe ít bị cản trở, khác với giới hạn tốc độ cho phép. FFS tùy chọn chỉ dùng cho HCM LOS tham khảo (hcm_los_proxy), không thay thế tốc độ tham chiếu của SPI và không tạo đánh giá HCM chính thức.</p>
      <p>Cần đủ xe có tốc độ hợp lệ (mặc định 3), ROI hiệu chuẩn đúng và tốc độ tham chiếu &gt; 0. Thiếu dữ liệu hiển thị --, không có nghĩa đường thông thoáng. UNKNOWN: chưa đủ dữ liệu; STALE: dữ liệu đã cũ.</p>
      <p>Trạng thái cần duy trì đủ thời gian xác nhận (mặc định 10 giây), nên màu/trạng thái có thể khác điểm tức thời. Ưu tiên trạng thái ổn định Jetson trả về.</p>
      <p>ROI chứa xe chờ đèn đỏ có thể cho tốc độ thấp dù không ùn tắc kéo dài. Kiểm tra kích thước ROI thực và quan sát nhiều chu kỳ đèn; v3 không tự loại trừ thời gian đèn đỏ.</p>
      <p>Điều khiển Jetson: lấy khung hình → vẽ ROI → lưu cấu hình → chờ xác nhận. Nếu pipeline đang chạy, Dừng rồi Chạy lại để áp dụng cấu hình mới.</p>
      <p>Đo hiệu năng Jetson (khác với SPI): đặt AUTO_MEASURE=1 trong môi trường chạy Jetson rồi khởi động lại agent nếu vừa đổi môi trường. Mỗi lần Chạy pipeline sẽ tự đo; MEASURE_INTERVAL là chu kỳ lấy mẫu (giây), MEASURE_WARMUP là thời gian bỏ qua lúc khởi động. MEASURE_OUT chọn thư mục báo cáo trên Jetson (mặc định bench_results). Khi video kết thúc hoặc dừng bình thường, xem metrics.csv, summary.json và summary.md trong thư mục phiên đo. Kiểm tra log [MEASURE] để biết đã khởi động hay gặp lỗi. FPS xử lý không phải FPS gốc video; phép đo hiệu năng không đánh giá độ chính xác nhận diện hoặc tốc độ xe. Các chỉ số phần cứng cần tegrastats trên Jetson; chưa có màn hình tải báo cáo benchmark trên WebGIS.</p>
    </div>
  </details>;
}
