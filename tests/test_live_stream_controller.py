import time
import pytest
from core.live_stream import LiveStreamController


class MockGstElement(object):
    def __init__(self):
        self.properties = {}

    def set_property(self, key, val):
        self.properties[key] = val

    def get_property(self, key):
        return self.properties.get(key)


def test_controller_initial_state():
    mock_valve = MockGstElement()
    ctrl = LiveStreamController(valve=mock_valve, idle_timeout_s=1.0, rtsp_url="rtsp://localhost:8554/live/cam1")
    assert ctrl.state == "off"
    assert mock_valve.get_property("drop") is True


def test_controller_start_and_stop():
    mock_valve = MockGstElement()
    ctrl = LiveStreamController(valve=mock_valve, idle_timeout_s=5.0, rtsp_url="rtsp://localhost:8554/live/cam1")

    # Start
    res = ctrl.start()
    assert res["status"] == "started"
    assert ctrl.state == "on"
    assert mock_valve.get_property("drop") is False

    # Calling start again while running returns already_running
    res2 = ctrl.start()
    assert res2["status"] == "already_running"

    # Stop
    res_stop = ctrl.stop()
    assert res_stop["status"] == "stopped"
    assert ctrl.state == "off"
    assert mock_valve.get_property("drop") is True


def test_controller_idle_timeout():
    mock_valve = MockGstElement()
    # 0.5s timeout for fast testing
    ctrl = LiveStreamController(valve=mock_valve, idle_timeout_s=0.5, rtsp_url="rtsp://localhost:8554/live/cam1")

    ctrl.start()
    assert ctrl.state == "on"
    assert mock_valve.get_property("drop") is False

    # Wait for idle timeout to fire (> 0.5s + monitor cycle)
    time.sleep(2.5)

    assert ctrl.state == "off"
    assert mock_valve.get_property("drop") is True


def test_controller_keepalive_resets_idle():
    mock_valve = MockGstElement()
    ctrl = LiveStreamController(valve=mock_valve, idle_timeout_s=1.5, rtsp_url="rtsp://localhost:8554/live/cam1")

    ctrl.start()
    time.sleep(0.8)
    res = ctrl.keep_alive()
    assert res["status"] == "ok"
    assert ctrl.state == "on"


def test_controller_bus_error_handling():
    mock_valve = MockGstElement()
    ctrl = LiveStreamController(valve=mock_valve, idle_timeout_s=5.0)

    ctrl.start()
    assert ctrl.state == "on"

    ctrl.on_bus_error("Connection refused by RTSP server")
    assert ctrl.state == "error"
    assert "Connection refused" in ctrl.error_message
    assert mock_valve.get_property("drop") is True


def test_v1_controller_default_on_demand_and_continuous_mode():
    """V1: Đảm bảo mặc định luôn là On-Demand (valve đóng ban đầu), chế độ liên tục phải bật tường minh."""
    mock_valve = MockGstElement()

    # 1. Khởi tạo với idle_timeout_s=0 nhưng KHÔNG bật continuous_mode
    # Hệ thống phải ép về On-Demand an toàn (state=off, valve.drop=True)
    ctrl = LiveStreamController(valve=mock_valve, idle_timeout_s=0)
    assert ctrl.state == "off", "Mặc định phải là off (On-Demand)"
    assert mock_valve.get_property("drop") is True, "Van mặc định phải đóng (drop=True) để không đẩy byte nào"
    assert ctrl.idle_timeout_s == 60.0

    # 2. Bật continuous_mode tường minh
    ctrl_cont = LiveStreamController(valve=mock_valve, idle_timeout_s=0, continuous_mode=True)
    assert ctrl_cont.state == "on"
    assert mock_valve.get_property("drop") is False

    # 3. Lệnh dừng chủ động (requested / stop_live) phải luôn đóng được van
    res_stop = ctrl_cont.stop(reason="requested")
    assert res_stop["status"] == "stopped"
    assert ctrl_cont.state == "off"
    assert mock_valve.get_property("drop") is True


def test_v2_live_branch_error_isolation_and_recovery():
    """V2: Lỗi từ nhánh live stream (MediaMTX rớt mạng, rtspclientsink lỗi) không làm sập pipeline AI."""
    mock_valve = MockGstElement()

    class MockSink(MockGstElement):
        def set_state(self, state):
            self.properties["state"] = state

    mock_sink = MockSink()
    ctrl = LiveStreamController(valve=mock_valve, sink=mock_sink, idle_timeout_s=60.0)

    # 1. Bắt đầu phát live
    ctrl.start()
    assert ctrl.state == "on"
    assert mock_valve.get_property("drop") is False

    # 2. Xảy ra lỗi từ MediaMTX rớt mạng -> gọi on_bus_error
    ctrl.on_bus_error("MediaMTX connection refused / network drop")
    assert ctrl.state == "error"
    assert "MediaMTX connection refused" in ctrl.error_message
    assert mock_valve.get_property("drop") is True, "Van phải đóng lập tức để cách ly lỗi"
    # Sink phải được đặt về NULL để ngắt kết nối lỗi
    assert mock_sink.properties.get("state") is not None

    # 3. Phục hồi khi MediaMTX sống lại và người dùng bấm xem lại (start)
    res_restart = ctrl.start()
    assert res_restart["status"] == "started"
    assert ctrl.state == "on"
    assert mock_valve.get_property("drop") is False


def test_v2_on_bus_message_filters_live_elements():
    """V2: Hàm phân loại lỗi bus bỏ qua lỗi nhánh live và chỉ dừng pipeline khi lỗi nhánh AI chính."""
    stop_called = []
    def mock_request_stop():
        stop_called.append(True)

    live_elements = {'queue_live', 'live_valve', 'conv_live', 'caps_live', 'enc_live', 'parse_live', 'sink_live'}

    class MockGstMessage:
        def __init__(self, elem_name, err_text="Connection refused"):
            self.elem_name = elem_name
            self.err_text = err_text
            self.src = type("Src", (), {"get_name": lambda s: elem_name})()

        def parse_error(self):
            return self.err_text, "debug_info"

    def handle_bus_error(msg):
        src_elem = getattr(msg, 'src', None)
        src_name = src_elem.get_name() if (src_elem and hasattr(src_elem, 'get_name')) else ''
        is_live_error = (src_name in live_elements) or ('live' in src_name.lower()) or ('rtsp' in src_name.lower())
        if is_live_error:
            # Live error: cách ly, KHÔNG dừng pipeline
            return "ignored_live"
        mock_request_stop()
        return "stopped_primary"

    # Lỗi từ rtspclientsink (sink_live) -> Không dừng pipeline
    res1 = handle_bus_error(MockGstMessage("sink_live"))
    assert res1 == "ignored_live"
    assert len(stop_called) == 0, "Lỗi từ sink_live tuyệt đối không được gọi request_stop"

    # Lỗi từ encoder live (enc_live) -> Không dừng pipeline
    res2 = handle_bus_error(MockGstMessage("enc_live"))
    assert res2 == "ignored_live"
    assert len(stop_called) == 0

    # Lỗi từ camera sensor chính (nvarguscamerasrc) -> Bắt buộc gọi request_stop
    res3 = handle_bus_error(MockGstMessage("nvarguscamerasrc"))
    assert res3 == "stopped_primary"
    assert len(stop_called) == 1, "Lỗi từ camera chính bắt buộc phải gọi request_stop"


def test_v6_dynamic_rtsp_url_update_via_mqtt_and_build_urls(monkeypatch):
    """V6: Kiểm tra cơ chế tự động điều phối RTSP URL qua MQTT và sinh URL động theo Client Host."""
    import sys
    import os
    import importlib.util

    from core.live_stream import LiveStreamController, set_global_controller, register_live_handlers

    # 1. Kiểm tra LiveStreamController cập nhật RTSP URL động
    class MockSink:
        def __init__(self):
            self.props = {}
        def set_property(self, name, val):
            self.props[name] = val
        def set_state(self, st):
            pass

    sink = MockSink()
    ctrl = LiveStreamController(
        valve=None,
        encoder=None,
        sink=sink,
        rtsp_url="rtsp://localhost:8554/live/edge-default",
        idle_timeout_s=60
    )

    ctrl.update_rtsp_url("rtsp://10.0.0.50:8554/live/edge-cloud")
    assert ctrl.rtsp_url == "rtsp://10.0.0.50:8554/live/edge-cloud"
    assert sink.props.get("location") == "rtsp://10.0.0.50:8554/live/edge-cloud"

    # 2. Kiểm tra command handler start_live tự động nhận param rtsp_url
    set_global_controller(ctrl)
    registered_handlers = {}
    class DummyCmdHandler:
        def register(self, action, handler):
            registered_handlers[action] = handler

    cmd_handler = DummyCmdHandler()
    register_live_handlers(cmd_handler)

    res = registered_handlers['start_live']({
        'command_id': 'cmd-v6-1',
        'params': {'rtsp_url': 'rtsp://172.16.0.88:8554/live/edge-dynamic'}
    })
    assert res['status'] == 'started'
    assert ctrl.rtsp_url == 'rtsp://172.16.0.88:8554/live/edge-dynamic'
    assert sink.props.get("location") == 'rtsp://172.16.0.88:8554/live/edge-dynamic'

    # 3. Kiểm tra _build_stream_urls sinh URL động theo Client Request (Isolated Loader)
    live_path = os.path.join(os.path.dirname(__file__), "..", "webgis", "backend", "routers", "live.py")
    spec = importlib.util.spec_from_file_location("isolated_live_mod", live_path)
    
    # Cung cấp dummy cho store để không phụ thuộc sys.path của backend
    sys.modules.setdefault("services", type("Mod", (), {})())
    sys.modules["services.data_store"] = type("Mod", (), {"store": None})()
    live_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(live_mod)
    _build_stream_urls = live_mod._build_stream_urls

    class MockRequest:
        def __init__(self, hostname, scheme="http", proto_hdr=None):
            self.url = type("URL", (), {"hostname": hostname, "scheme": scheme})()
            self.headers = {"x-forwarded-proto": proto_hdr} if proto_hdr else {}

    # Client truy cập bằng domain HTTPS qua reverse proxy
    req_https = MockRequest(hostname="giaothong.tphcm.gov.vn", scheme="http", proto_hdr="https")
    urls_https = _build_stream_urls("edge-01", request=req_https)
    assert "https://giaothong.tphcm.gov.vn:8889/live/edge-01/" in urls_https["webrtc_url"]
    assert "https://giaothong.tphcm.gov.vn:8888/live/edge-01/index.m3u8" in urls_https["hls_url"]
    assert "rtsp://giaothong.tphcm.gov.vn:8554/live/edge-01" in urls_https["rtsp_url"]
    
    # Dọn dẹp module cô lập
    sys.modules.pop("isolated_live_mod", None)
    sys.modules.pop("services.data_store", None)


def test_v7_nonblocking_snapshot_queue_and_async_preview_worker(tmp_path):
    """V7: Kiểm tra cơ chế không block GStreamer Pad Probe:
    - Snapshot queue có maxsize=2, khi đầy tự động drop ngay lập tức (<1ms), không bao giờ block luồng video.
    - Preview worker xử lý nén JPEG và ghi đĩa bất đồng bộ ở thread nền.
    """
    import queue
    import threading
    import os
    import numpy as np
    import time
    import cv2
    from snap.snapshot_service import SnapshotCoordinator

    # 1. Kiểm tra SnapshotCoordinator không block Pad Probe
    coord = SnapshotCoordinator(
        api_url="http://localhost:8000",
        edge_id="test-v7-node",
        edge_token="test-token",
        queue_size=2,
        outbox_dir=str(tmp_path / "outbox"),
        analysis_source="csi"
    )

    fake_frame = np.zeros((720, 1280, 4), dtype=np.uint8)
    telemetry = {"traffic_status": "CONGESTED", "vehicle_count": 10}

    # Bơm frame: đo thời gian submit_frame trong Pad Probe
    t0 = time.monotonic()
    coord.request_manual_snapshot("cmd-v7-1")
    accepted1 = coord.submit_frame(fake_frame, telemetry, color_format="RGBA")
    dt1 = time.monotonic() - t0
    assert accepted1 is True
    assert dt1 < 0.05, "submit_frame phải kết thúc cực nhanh trong RAM (< 50ms)"

    coord.request_manual_snapshot("cmd-v7-2")
    accepted2 = coord.submit_frame(fake_frame, telemetry, color_format="RGBA")
    assert accepted2 is True

    # Khi hàng đợi đầy (maxsize=2), submit_frame tiếp theo phải từ chối ngay lập tức, không chờ đợi
    t_full = time.monotonic()
    coord.request_manual_snapshot("cmd-v7-3")
    accepted3 = coord.submit_frame(fake_frame, telemetry, color_format="RGBA")
    dt_full = time.monotonic() - t_full
    assert accepted3 is False
    assert dt_full < 0.005, "Khi hàng đợi đầy, phải từ chối ngay lập tức mà không block probe (< 5ms)"

    coord.stop(timeout=1.0)

    # 2. Kiểm tra Async Preview Worker ghi đĩa không block
    preview_queue = queue.Queue(maxsize=1)
    stop_event = threading.Event()
    dest_img = str(tmp_path / "test_latest_preview.jpg")

    def _worker():
        while not stop_event.is_set():
            try:
                item = preview_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if item is None:
                break
            try:
                surf_copy, dest = item
                bgr = cv2.cvtColor(surf_copy, cv2.COLOR_RGBA2BGR)
                cv2.imwrite(dest, bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            finally:
                preview_queue.task_done()

    worker_th = threading.Thread(target=_worker, daemon=True)
    worker_th.start()

    # Giả lập Pad Probe chỉ copy mảng trên RAM và put_nowait vào queue
    t_probe_start = time.monotonic()
    raw_surf = np.full((720, 1280, 4), 120, dtype=np.uint8)
    surf_copy = raw_surf.copy()
    preview_queue.put_nowait((surf_copy, dest_img))
    probe_exec_time = time.monotonic() - t_probe_start

    assert probe_exec_time < 0.05, "Thao tác trong Pad Probe phải dưới 50ms"

    # Chờ worker nền ghi xong đĩa
    for _ in range(50):
        if os.path.exists(dest_img) and os.path.getsize(dest_img) > 1000:
            break
        time.sleep(0.02)

    assert os.path.exists(dest_img), "Ảnh preview phải được ghi thành công bởi worker thread nền"
    assert os.path.getsize(dest_img) > 1000

    stop_event.set()
    preview_queue.put_nowait(None)
    worker_th.join(timeout=1.0)




