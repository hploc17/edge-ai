# EDGE AI + WEBGIS HEATMAP FEASIBILITY AUDIT

**Phạm vi:** đánh giá camera/YOLO/tracking/telemetry và trực quan hóa MapLibre; không triển khai hoặc chỉnh mã nguồn.

## Quy ước dẫn chứng

- `[STANDARD]`: tiêu chuẩn chính thức.
- `[PAPER]`: nghiên cứu peer-reviewed.
- `[OFFICIAL_DOC]`: tài liệu chính thức của nhà cung cấp hoặc cơ quan.
- `[CODE]`: xác minh trực tiếp trong repository.
- `[PROJECT_DESIGN]`: quyết định của dự án.
- `[UNVERIFIED]`: chưa truy cập hoặc xác minh được.

---

# 1. Executive Summary

**Kết luận: CONDITIONAL GO**

Hệ thống hiện có thể cung cấp một dashboard giao thông camera-based bằng ba đại lượng quan sát:

- PCE density hoặc density thô;
- stopped ratio;
- representative speed;

không cần Fuzzy, Random Forest hoặc Traffic Score mới.

Điều kiện trước triển khai:

1. Xác nhận PCE weight bằng tài liệu tiêu chuẩn chính thức.
2. Xác nhận homography/road length/sampling window bằng thực địa.
3. Thêm data-quality và timestamp/source mode rõ ràng.
4. Chỉ hiển thị dữ liệu tại phạm vi camera/đoạn được liên kết; không tạo vùng đo giữa camera.
5. Chạy shadow mode và manual validation trước khi dùng màu lớp GIS.

**Khuyến nghị:**

- Không dùng Point Heatmap làm mặc định.
- Dùng Camera Marker + Road Segment Thematic Map.
- Hiển thị PCE density như metric chi tiết, nhưng không coi color mặc định là congestion truth.
- Hiển thị stopped ratio và median speed theo từng lớp/marker nếu có đủ data quality.
- Không tạo Traffic Score.
- Không sửa V1/V2/V3 trong giai đoạn này.

---

# 2. Requirement Alignment

Mục tiêu Heatmap/WebGIS hiện đúng với phương án quan sát đa chỉ số:

- Edge AI đã đo vehicle presence, track speed, PCE density và stopped ratio.
- Backend đã nhận MQTT 1 Hz, lưu telemetry và phát WebSocket.
- Frontend đã có MapLibre, camera markers, FOV cones và road segment LineLayers.
- Repository chưa có heatmap point GeoJSON độc lập cho density/speed/stopped; phần roadmap hiện chỉ tô segment theo congestion_score.

Phương án không nên nhắm tới classifier. Cần giữ các metric độc lập và cảnh báo data status.

---

# 3. Scientific Evidence Matrix

| Thành phần | Nguồn | Công thức/tài liệu | Mức xác minh | Khoảng trống |
|---|---|---|---|---|
| Detection | YOLO11 + DeepStream, NVIDIA official JetPack blog is JetPack 6 YOLOv8 | YOLO detection + NvDCF | `[OFFICIAL_DOC]` kiến trúc; `[CODE]` implementation Jetson 4.6 | Không dùng được JetPack 6 sample as-is |
| Tracking | DeepStream NvDCF | metadata object ID/tracking | `[CODE]` tracker config + speed estimator | Không có manual track-switch benchmark |
| Current presence count | Project method | confirmed Track IDs in Analysis ROI | `[CODE]` presence counter | Không bằng cross-section flow |
| Density direct | Fundamental traffic variables | $k=N/(L\times n)$ | `[STANDARD]` khi định nghĩa density; `[CODE]` implementation | ROI length/lanes must be validated |
| PCE density | TCVN 4054:2005 claim | $\sum PCE_i/(L\times n)$ | `[UNVERIFIED]` exact scope and factor values | Không truy cập được text chính thức trong environment |
| Speed | Homography track displacement | linear regression over track history | `[CODE]` | Không có space-mean-speed validation |
| Stopped ratio | Project rule | stopped count/evaluated valid tracks | `[PROJECT_DESIGN]` | 5 km/h threshold needs calibration/ground truth |
| Heatmap weight | MapLibre official example | GeoJSON point + weight/intensity/radius/color | `[OFFICIAL_DOC]` | No traffic camera interpretation |
| Gis segment | Existing repository implementation | LineString + road width + traffic color | `[CODE]` | Segment geometry and camera coverage may differ |

---

# 4. Repository Evidence Map

## Edge pipeline

- [main.py](D:/Project/Project/main.py:895): nhận detection/tracking, tính metrics và telemetry.
- [main.py](D:/Project/Project/main.py:1026): queue/publish 1 Hz.
- [config_tracker_optimized.yml](D:/Project/Project/configs/config_tracker_optimized.yml): cấu hình NvDCF.
- [roi_manager.py](D:/Project/Project/spatial/roi_manager.py:10): quản lý ROI/homography geometry.
- [roi_traffic_nano.json](D:/Project/Project/configs/roi_traffic_nano.json:1): road_length 50 m, road_width 7 m, lane_count 2.

## Count/density/stopped/speed

- [presence_counter.py](D:/Project/Project/analytics/presence_counter.py:61): enter 0.10 s, exit 0.25 s, lost 1.0 s.
- [presence_counter.py](D:/Project/Project/analytics/presence_counter.py:143): snapshot confirmed Track IDs.
- [speed_estimator.py](D:/Project/Project/analytics/speed_estimator.py:277): history 2 s, minimum 0.8 s, smoothing 0.25.
- [speed_estimator.py](D:/Project/Project/analytics/speed_estimator.py:329): bottom-center Homography và linear regression.
- [traffic_classifier.py](D:/Project/Project/analytics/traffic_classifier.py:403): filter speed theo current Track IDs.
- [traffic_classifier.py](D:/Project/Project/analytics/traffic_classifier.py:497): density thô `N/(road_length×lane)`.
- [traffic_classifier.py](D:/Project/Project/analytics/traffic_classifier.py:506): PCE weight theo class.
- [traffic_classifier.py](D:/Project/Project/analytics/traffic_classifier.py:471): stopped count/ratio.

## MQTT/backend/frontend

- [mqtt_client.py](D:/Project/Project/communication/mqtt_client.py:320): telemetry payload 1 Hz.
- [mqtt_service.py](D:/Project/Project/webgis/backend/services/mqtt_service.py): broker subscription, telemetry broadcast.
- [data_store.py](D:/Project/Project/webgis/backend/services/data_store.py:830): update realtime node.
- [data_store.py](D:/Project/Project/webgis/backend/services/data_store.py:1210): node/segment GeoJSON.
- [gis.py](D:/Project/Project/webgis/backend/routers/gis.py): `/nodes`, `/segments`, `/summary`.
- [WebGISMap.tsx](D:/Project/Project/webgis/frontend/src/components/Map/WebGISMap.tsx:230): traffic segment line source/layers.
- [WebGISMap.tsx](D:/Project/Project/webgis/frontend/src/components/Map/WebGISMap.tsx:646): marker and FOV update.
- [trafficStatus.ts](D:/Project/Project/webgis/frontend/src/lib/trafficStatus.ts): three-state label và stale handling.

---

# 5. Traffic Metric Validity

## 5.1 Vehicle count

`[CODE]` `RoiPresenceCounter` đếm xe hiện diện có xác nhận trong Analysis ROI, không phải vehicle volume qua cross-section.

Hạn chế:

- Track ID switch có thể reset lịch sử.
- Lost Track có thể làm xe mất khỏi density.
- ROI ra/vào có hysteresis.
- Không có manual count ground truth hiện tại.

## 5.2 Density

Công thức hiện tại:

$$
D_{\text{raw}}=
\frac{N_{\text{confirmed}}}
{L_{\text{km}}\times n_{\text{lane}}}
\quad [veh/km/lane]
$$

$$
D_{\text{PCE}}=
\frac{\sum PCE_i}
{L_{\text{km}}\times n_{\text{lane}}}
\quad [PCE/km/lane]
$$

`[CODE]` PCE weights gồm motorbike 0.30, bicycle 0.20, car 1.0, truck 1.8, bus 2.0, vehicle_fire 2.0.

`[UNVERIFIED]` TCVN 4054:2005 exact scope and these motorcycle factors.

Trình bày:

- Có thể dùng PCE density làm density visualization default.
- Không gọi PCE density là `density in paper` hoặc HCM LOS density.
- Không công bố PCU/km/lane trên nhiều camera trừ khi road length/lane count/ROI geometry tương đương.

## 5.3 Stopped ratio

`[CODE]`

$$
R_{\text{stop}}=
\frac{N_{\text{stopped,moved tracks}}}
{N_{\text{evaluated tracks}}}
$$

Ngưỡng mặc định là `< 5 km/h`, và xe `has_moved=False` bị loại khỏi stopped evidence.

Rủi ro:

- Mẫu số 0 hoặc nhỏ làm tỷ lệ không ổn định.
- 100% không nhất thiết nghĩa congestion nếu một xe dừng.
- Không bằng queue length.
- Không bằng dwell time.
- Không bằng congestion.

Nên hiển thị stopped count và valid speed count cùng stopped ratio.

## 5.4 Representative speed

`[CODE]`

- Speed theo từng track.
- Mean và median được tính tại 1 Hz snapshot.
- Xe đứng yên có thể có 0 km/h sau displacement nhỏ.
- Xe chưa từng di chuyển được loại trong một số logic stopped.
- Không có bằng chứng median track speed là space mean speed.

Hiển thị median hoặc mean phải ghi tên và valid speed count.

---

# 6. Heatmap Normalization

## 6.1 Point heatmap weight

Công thức visualization-only:

$$
W_D=
\operatorname{clip}\left(
\frac{D_{\text{PCE}}}{D_{\text{ref}}},
0,1
\right)
$$

`[PROJECT_DESIGN]` $W_D$ chỉ là weight cho màu MapLibre.

Không có tiêu chuẩn nào xác nhận $D_{\text{ref}}$ là ngưỡng congestion.

## 6.2 Xác lập Dref

Không gán 100/150/200.

Phương pháp đề xuất để kiểm chứng:

1. Thu nhiều telemetry từ mỗi camera.
2. Loại empty/stale/invalid.
3. Chia theo camera geometry và time window.
4. Dùng quan sát thực địa hoặc ground-truth occupancy thay cho heuristic.
5. Xác lập `D_ref` bằng phân vị đã đăng ký, ví dụ p95 trong giai đoạn reference measured, không dùng p95 để claim congestion threshold.
6. Nếu so sánh nhiều camera, bắt buộc cùng unit/road length/lane count/calibration.

Các mức:

- Fixed `D_ref`: chỉ dùng nội bộ UI, không so sánh tuyến.
- Empirical `D_ref` per-camera: phù hợp thang so sánh camera, cần lịch hiệu chuẩn.
- Shared `D_ref`: chỉ dùng khi camera và geometry tương đương.

## 6.3 0 và missing

- 0 vehicle + valid data: 0 weight.
- No valid speed: speed weight unavailable.
- Stale/offline: không weight, hiển thị gray/offline.
- Value > threshold: clip 1.
- Extreme values: winsorization hoặc percentile reference, không vẽ trực tiếp thành 100%.

## 6.4 Stopped ratio

Có thể hiển thị trực tiếp 0-1 nhưng bắt buộc:

- stopped count;
- valid speed count;
- sample window;
- data quality.

## 6.5 Speed

Để dùng speed heatmap:

$$
W_v=\operatorname{clip}\left(
\frac{v_{\max}-v}{v_{\max}-v_{\min}},
0,1
\right)
$$

`v_max/v_min` chưa xác lập. Không dùng công thức này nếu thiếu free-flow calibration.

Better: hiển thị tốc độ bằng legend numeric; color chỉ là categorical/low-vs-high speed, không dùng congestion conclusion.

---

# 7. GIS Visualization Alternatives

## GIS-A Point Heatmap

Ưu điểm:

- Nhanh.
- Hấp dẫn cho nhiều điểm.

Hạn chế:

- Heat map làm nổi vùng không có camera.
- Hai camera tạo vùng màu ảo giữa camera.
- Radius dễ bị hiểu là phạm vi quan sát.
- Không phù hợp khi chỉ 1-2 camera.

**Không khuyến nghị mặc định.**

## GIS-B Camera Marker

Ưu điểm:

- Định vị đúng điểm đo.
- Hiển thị pop-up với metric.
- Dễ tách density/speed/stopped.
- So sánh camera dễ.
- Đơn giản/ít risk diễn giải.

**Khuyến nghị làm view mặc định.**

## GIS-C Road Segment Thematic

`[CODE]` repository đã có OSM/road LineString và segment update.

Hạn chế:

- Không rõ segment geometry có đúng chiều/ROI coverage không.
- One segment with many cameras needs aggregation rule.
- Không tô toàn tuyến dài hơn phạm vi camera.
- Need exact mapping edge/camera/segment/heading/direction.

**Khuyến nghị làm layer bổ sung**, chỉ ở đoạn segment đã được xác nhận đo, không dùng heatmap glow để suy diễn đoạn ngoài camera.

## Kết luận

**GIS-B là mặc định; GIS-C là lớp tuyến bổ sung; GIS-A chỉ là optional exploratory layer** nếu có đủ dense camera và legend/radius rõ ràng.

---

# 8. MQTT and Backend Compatibility

`[CODE]` MQTT payload hiện có:

- edge_id/camera_id/segment_id;
- timestamp;
- current_vehicle_count;
- median/avg speed;
- density raw/PCE;
- stopped count/ratio;
- traffic status/congestion score;
- source-related fields and data_quality fields.

`[CODE]` FastAPI nhận MQTT + WebSocket + SQLite timeline.

Timestamp hiện cần phân biệt:

- video frame/event timestamp;
- Jetson processing timestamp;
- backend receive timestamp;
- frontend display timestamp.

Với replay: `source_mode=file/replay`; không công bố là live actual road.

Mẫu telemetry đề xuất:

```json
{
  "camera_id": "CAM_01",
  "timestamp": "2026-...",
  "source_mode": "live",
  "vehicle_count": 0,
  "density_pce_per_km_lane": 0.0,
  "stopped_count": 0,
  "valid_speed_count": 0,
  "stopped_ratio": null,
  "median_speed_kmh": null,
  "data_quality": "VALID"
}
```

`timestamp` là backend/telemetry publish; có thể bổ sung frame timestamp nhưng không phá schema cũ.

---

# 9. Real-Time and Multi-Camera Feasibility

`[CODE]`

- Telemetry 1 Hz.
- MQTT WebSocket cập nhật frontend.
- Backend stale watchdog >20 s, liveness offline >25 s.
- Frontend marks stale if older than 30 s.
- Multi-camera Node GeoJSON and segment aggregation already exist.

Chưa benchmark:

- Jetson latency.
- MQTT-to-WebSocket latency.
- frontend render cost.
- RAM/CPU impact of heatmap.

Không viết số giả.

---

# 10. Edge AI Engineering Assessment

NVIDIA official page is JetPack 6/YOLOv8/NVIDIA JPS; project uses JetPack 4.6.1/YOLO11/DeepStream 6.0.1. Các phần dùng:

- YOLO object detection;
- NvDCF tracking;
- tripwire/trajectory analytics;

có thể lấy ý tưởng; không sao chép JPS pipeline vì incompatible.

Việc thêm markers/independent metrics không cần thêm YOLO model hoặc deepstream changes.

Heatmap weight computation should be at backend/frontend 1 Hz, not inside DeepStream frame loop.

---

# 11. Experimental Validation Plan

## Detection

- precision, recall, mAP@0.5;
- motorbike recall;
- class confusion;
- occlusion/light conditions.

## Count/density

- manual count;
- manual PCE count;
- MAE và RMSE;
- repeated route calibration;
- Track ID switch and ROI exit/enter events.

## Speed

- ground-truth speed bằng marker/GPS;
- MAE/RMSE;
- speed stability for stopped/slowed vehicles;
- Homography error by corner movement.

## Stopped ratio

- manual stopped count;
- sensitivity 3/5/7 km/h;
- valid speed count;
- red-light and real queue clips.

## WebGIS

- timestamp-to-display latency;
- live vs replay flag;
- stale/offline state;
- camera position accuracy;
- legend/normalization correctness;
- no extrapolated heat outside cameras.

---

# 12. Academic Validity

## Có nguồn rõ

- Detection/tracking: NVIDIA official docs.
- Vehicle flow/density/speed: FHWA Traffic Monitoring concepts, subject to official text access.
- PCE concept: TCVN 4054:2005 claim, exact applicability `[UNVERIFIED]`.
- GIS weight/render: MapLibre official docs.
- Trajectory/flow: OpenTrafficCam and OTAnalytics.

## Do dự án thiết kế

- PCE mapping weights.
- 5 km/h stopped threshold.
- 50 m road length and 7 m width config.
- PCE normalization reference.
- Marker/segment/heatmap visual choice.
- 1 Hz telemetry sampling.

## Giá trị khóa luận

Nên mô tả là:

- tích hợp Edge AI metrics;
- chuẩn hóa và truyền telemetry;
- trực quan hóa GIS theo phạm vi quan sát;
- data quality and replay/live separation;

không mô tả là phát minh classifier/Traffic Score.

---

# 13. Risks and Limitations

1. PCE density không có verified TCVN full text.
2. 5 km/h threshold chưa ground truth.
3. Median track speed không equivalent space mean speed.
4. Road segment could imply coverage beyond camera.
5. Heatmap radius can imply unmeasured range.
6. Replay video can be mistaken live.
7. Stopped ratio unstable with few vehicles.
8. Homography quality varies by camera.
9. Track switches affect count/density/speed.
10. Dref without field protocol is arbitrary.
11. Multi-camera cross-camera metric comparison needs common calibration.
12. No Jetson benchmark for visualization overhead.

---

# 14. Final Recommendation

## Chỉ số heatmap

- Không tạo một Traffic Score.
- Không dùng Point Heatmap làm mặc định.
- Camera Marker là view mặc định.
- PCE density là metric density cho popup/legend; khi có đủ calibration mới dùng segment thematic.
- Stopped ratio and speed remain separate layers/views.

## PCE density

Dùng cho thống kê trong ROI theo PCU/km/lane sau khi xác minh weights và camera geometry. Không claim TCVN formula nếu exact scope chưa truy cập.

## Stopped Ratio

Hiển thị khi valid_speed_count >= minimum và có stopped count. Always show `UNKNOWN`/insufficient for low sample.

## Speed

Hiển thị numeric median speed; optional reverse-sequential color. Không mix with density heat weight.

## GIS

`GIS-B + GIS-C`, not GIS-A by default.

## Traffic Score

Không cần.

## V1/V2/V3

Không sửa; preserve as backend existing classification methods. Heatmap dashboard reads independent metrics.

## Mức thay đổi mã

- Small backend: expose PCE/stopped/valid speed in node GeoJSON and live states if absent.
- Small frontend: independent marker legend/popups/layer toggles.
- Optional segment: display measured coverage, without broad heat extrapolation.
- No YOLO/DeepStream/Homography/tracker changes required.

---

# 15. Implementation Roadmap

## Bắt buộc

1. Xác minh PCE factors and unit source.
2. Thêm `source_mode`, frame timestamp và received timestamp.
3. Thêm `valid_speed_count`, stopped count, PCE density in node GeoJSON.
4. Thêm stale/offline/missing states.
5. Giữ Camera Marker as primary.
6. Thêm legend and metric label.

## Nên làm

1. Manual calibration for 50 m ROI and homography.
2. Validate stopped threshold.
3. Add independent segment coverage geometry.
4. Add data quality in marker popup.
5. Add metric switch density/speed/stopped.

## Có thể hoãn

1. Point heatmap.
2. Cross-camera percentile normalization.
3. Historical heatmap animation.
4. 5-minute/10-minute forecast.

## Không cần

1. Fuzzy V4.
2. Random Forest.
3. Traffic Score.
4. DeepStream pipeline changes.
5. New YOLO model.

---

# 16. Academic Defense Questions

1. **Vì sao dùng Edge AI thay gửi video lên server?** `[OFFICIAL_DOC]` Edge processing reduces bandwidth/privacy risk and supports real-time metadata.
2. **YOLO11 có vai trò gì?** `[CODE]` Detection vehicle classes; not classification congestion.
3. **Tracking cần thiết để làm gì?** `[CODE]` Maintain Track ID/speed history/presence.
4. **Vì sao density là metric?** `[STANDARD]` Density is fundamental traffic variable and code provides direct PCE/vehicle density.
5. **Density cao có chắc congestion không?** Không. It is one observed metric.
6. **Stopped ratio nói gì?** Fraction stopped among evaluated tracks.
7. **Vì sao median speed?** `[CODE]` Project uses median for robustness; need not call space mean speed.
8. **Có cần Traffic Score?** No for this objective.
9. **Vì sao không dùng Fuzzy/RF?** Không cần classify; no independent labels.
10. **PCE source?** `[UNVERIFIED]` code references TCVN 4054:2005; exact official full text not verified.
11. **Density formula đúng không?** It is direct presence density; differs from flow/speed derived density.
12. **5 km/h stopped threshold source?** `[PROJECT_DESIGN]`, needs calibration.
13. **D_ref xác định thế nào?** Empirical per-camera percentile plus field validation; `[CALIBRATION_REQUIRED]`.
14. **Heatmap có phải AI không?** No, MapLibre visualizes normalized point/line weights.
15. **Camera phạm vi bao nhiêu?** 50 m configured length at current ROI; actual coverage requires survey.
16. **Có thể kết luận đoạn không camera không?** No.
17. **Một camera có point heatmap ý nghĩa không?** Low; marker is clearer.
18. **Thời gian thực chứng minh thế nào?** MQTT publish 1 Hz, server receipt, stale/watchdog and replay flag.
19. **Multi-camera mở rộng thế nào?** Node GeoJSON + segment linkage.
20. **Đóng góp khóa luận là gì?** System integration, independent traffic metrics, GIS visualization and validation protocol.
